"""
智答引擎（ZhiDa Engine）—— 定时学习调度器

定时从聊天记录中批量提取 Q&A 知识，避免实时处理对消息延迟的影响。
支持：
- 定时批量提取（如每 5 分钟）
- 空闲时段深度提取（使用 LLM 精确识别）
- 知识库定期清理（去重、合并相似 Q&A 对）

模块开关：settings.ENABLE_AUTO_LEARNING
"""

import asyncio
import time
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger

from app.core.config import settings
from app.services.learning.qa_extractor import qa_extractor, ChatMessage, QAPair


class SchedulerStatus(str, Enum):
    """调度器状态"""
    IDLE = "idle"
    RUNNING = "running"
    DEEP_EXTRACTING = "deep_extracting"  # 深度提取中
    CLEANING = "cleaning"


@dataclass
class ScheduleConfig:
    """调度配置"""
    batch_interval: int = 300       # 批量提取间隔（秒），默认 5 分钟
    deep_extract_interval: int = 3600  # 深度提取间隔（秒），默认 1 小时
    clean_interval: int = 86400     # 清理间隔（秒），默认 24 小时
    max_batch_size: int = 100       # 每批最多处理消息数
    idle_hours: list[int] = field(default_factory=lambda: [2, 3, 4])  # 深度提取时段（凌晨 2-4 点）


class LearningScheduler:
    """
    定时学习调度器 —— 批量处理聊天记录

    三层调度：
    1. 批量提取（高频）：每 5 分钟从消息缓冲中提取 Q&A 对
    2. 深度提取（低频）：空闲时段使用 LLM 精确识别边缘问题
    3. 知识清理（极低频）：每天去重合并相似 Q&A 对

    Usage:
        scheduler = LearningScheduler(config)

        # 注册消息缓冲回调
        scheduler.on_batch_process = my_handler

        # 启动调度器
        await scheduler.start()

        # 停止调度器
        await scheduler.stop()
    """

    def __init__(self, config: Optional[ScheduleConfig] = None):
        self.config = config or ScheduleConfig()
        self.status = SchedulerStatus.IDLE
        self._message_buffer: list[ChatMessage] = []
        self._tasks: list[asyncio.Task] = []
        self._running = False

        # 回调
        self.on_batch_process: Optional[Callable[[list[QAPair]], Awaitable[None]]] = None
        self.on_deep_extract: Optional[Callable[[list[QAPair]], Awaitable[None]]] = None
        self.on_clean: Optional[Callable[[int], Awaitable[None]]] = None  # removed_count

        # 统计
        self._total_extracted = 0
        self._last_batch_time: Optional[float] = None
        self._last_deep_time: Optional[float] = None
        self._last_clean_time: Optional[float] = None

    async def start(self):
        """启动调度器"""
        if self._running:
            return

        if not settings.ENABLE_AUTO_LEARNING:
            logger.info("自动学习已关闭，调度器不启动")
            return

        self._running = True
        self.status = SchedulerStatus.RUNNING

        # 启动定时任务
        self._tasks = [
            asyncio.create_task(self._batch_loop()),
            asyncio.create_task(self._deep_extract_loop()),
            asyncio.create_task(self._clean_loop()),
        ]

        logger.info(
            f"学习调度器启动: 批量间隔={self.config.batch_interval}s, "
            f"深度间隔={self.config.deep_extract_interval}s, "
            f"清理间隔={self.config.clean_interval}s"
        )

    async def stop(self):
        """停止调度器"""
        self._running = False
        self.status = SchedulerStatus.IDLE

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tasks = []

        logger.info(f"学习调度器停止，共提取 {self._total_extracted} 个问答对")

    async def add_messages(self, messages: list[ChatMessage]):
        """添加消息到缓冲区"""
        self._message_buffer.extend(messages)

        # 缓冲区大小限制
        if len(self._message_buffer) > self.config.max_batch_size * 10:
            self._message_buffer = self._message_buffer[-self.config.max_batch_size * 10:]

    async def _batch_loop(self):
        """批量提取循环"""
        while self._running:
            try:
                await asyncio.sleep(self.config.batch_interval)

                if self._message_buffer:
                    await self._run_batch_extract()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"批量提取异常: {e}")

    async def _deep_extract_loop(self):
        """深度提取循环 —— 空闲时段执行"""
        from datetime import datetime

        while self._running:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次

                current_hour = datetime.now().hour

                # 在空闲时段进行深度提取
                if current_hour in self.config.idle_hours:
                    # 检查是否已到间隔
                    if (self._last_deep_time is None or
                            time.time() - self._last_deep_time >= self.config.deep_extract_interval):
                        await self._run_deep_extract()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"深度提取异常: {e}")

    async def _clean_loop(self):
        """知识清理循环"""
        while self._running:
            try:
                await asyncio.sleep(self.config.clean_interval)
                await self._run_clean()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理异常: {e}")

    async def _run_batch_extract(self):
        """执行批量提取"""
        self.status = SchedulerStatus.RUNNING

        # 取出一批消息
        batch = self._message_buffer[:self.config.max_batch_size]
        self._message_buffer = self._message_buffer[self.config.max_batch_size:]

        if not batch:
            return

        logger.debug(f"批量提取: {len(batch)} 条消息")

        qa_pairs = await qa_extractor.extract_from_history(batch)
        self._total_extracted += len(qa_pairs)
        self._last_batch_time = time.time()

        if qa_pairs and self.on_batch_process:
            await self.on_batch_process(qa_pairs)

        self.status = SchedulerStatus.IDLE

    async def _run_deep_extract(self):
        """执行深度提取 —— 使用 LLM 精确识别"""
        self.status = SchedulerStatus.DEEP_EXTRACTING

        logger.info("开始深度提取...")

        # 使用 LLM 对缓冲区中的消息进行精确问题识别
        qa_pairs = []
        for msg in self._message_buffer[:20]:  # 限制数量，避免 Token 消耗过大
            try:
                is_q, confidence = await qa_extractor._detector.is_question_with_llm(msg)
                if is_q and confidence > 0.6:
                    # 已识别为问题，等待后续回答
                    result = await qa_extractor.process_message(msg)
                    if result:
                        qa_pairs.append(result)
            except Exception as e:
                logger.warning(f"深度提取单条消息失败: {e}")
                continue

        self._last_deep_time = time.time()

        if qa_pairs and self.on_deep_extract:
            await self.on_deep_extract(qa_pairs)

        self.status = SchedulerStatus.IDLE
        logger.info(f"深度提取完成: {len(qa_pairs)} 个问答对")

    async def _run_clean(self):
        """执行知识清理"""
        self.status = SchedulerStatus.CLEANING
        logger.info("开始知识清理...")

        # TODO: 实现去重合并
        # - 相似度 > 0.95 的 Q&A 对合并
        # - 删除长期未引用的 Q&A 对
        # - 更新质量评分

        removed = 0
        self._last_clean_time = time.time()

        if self.on_clean:
            await self.on_clean(removed)

        self.status = SchedulerStatus.IDLE
        logger.info(f"知识清理完成: 移除 {removed} 个问答对")

    def get_stats(self) -> dict:
        """获取调度器统计"""
        return {
            "status": self.status.value,
            "buffer_size": len(self._message_buffer),
            "total_extracted": self._total_extracted,
            "last_batch_time": self._last_batch_time,
            "last_deep_time": self._last_deep_time,
            "last_clean_time": self._last_clean_time,
        }


# 全局学习调度器
learning_scheduler = LearningScheduler()