"""
智答引擎（ZhiDa Engine）—— 实时消息监听器

持续监听指定群聊/联系人的聊天记录，实时提取 Q&A 知识。
支持多 Agent 同时监听不同渠道。

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


class ListenerStatus(str, Enum):
    """监听器状态"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class ListenerConfig:
    """监听器配置"""
    agent_id: int
    chat_id: str
    chat_name: str
    channel_type: str = "wechat"     # wechat/qq
    listen_mode: str = "all"         # all/mentioned/questions
    target_users: list[str] = field(default_factory=list)  # 目标用户列表（空=所有用户）
    enable_learning: bool = True
    auto_reply: bool = True


class MessageListener:
    """
    实时消息监听器 —— 持续监听聊天消息

    每个 Agent 的每个渠道可以启动一个独立的监听器。

    Usage:
        listener = MessageListener(config)

        # 注册消息回调
        listener.on_message = my_handler

        # 启动监听
        await listener.start()

        # 停止监听
        await listener.stop()
    """

    def __init__(self, config: ListenerConfig):
        self.config = config
        self.status = ListenerStatus.STOPPED
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._processor_task: Optional[asyncio.Task] = None
        self._start_time: Optional[float] = None

        # 消息处理回调
        self.on_message: Optional[Callable[[ChatMessage], Awaitable[None]]] = None
        self.on_qa_extracted: Optional[Callable[[QAPair], Awaitable[None]]] = None
        self.on_error: Optional[Callable[[Exception], Awaitable[None]]] = None

        # 统计
        self._message_count = 0
        self._qa_count = 0
        self._last_message_time: Optional[float] = None

    async def start(self):
        """启动监听器"""
        if self.status == ListenerStatus.RUNNING:
            logger.warning(f"监听器已在运行: {self.config.chat_name}")
            return

        self.status = ListenerStatus.RUNNING
        self._start_time = time.time()

        # 启动消息处理器
        self._processor_task = asyncio.create_task(self._process_messages())

        logger.info(f"监听器启动: {self.config.chat_name} (mode={self.config.listen_mode})")

    async def stop(self):
        """停止监听器"""
        self.status = ListenerStatus.STOPPED

        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

        logger.info(f"监听器停止: {self.config.chat_name}, 共处理 {self._message_count} 条消息, 提取 {self._qa_count} 个问答对")

    async def pause(self):
        """暂停监听"""
        self.status = ListenerStatus.PAUSED
        logger.info(f"监听器暂停: {self.config.chat_name}")

    async def resume(self):
        """恢复监听"""
        self.status = ListenerStatus.RUNNING
        logger.info(f"监听器恢复: {self.config.chat_name}")

    async def feed_message(self, raw_message: dict) -> Optional[ChatMessage]:
        """
        喂入一条原始消息 —— 由渠道适配器调用

        Args:
            raw_message: 渠道适配器转换后的消息字典

        Returns:
            转换后的 ChatMessage
        """
        if self.status != ListenerStatus.RUNNING:
            return None

        # 转换为标准消息格式
        message = self._parse_message(raw_message)
        if message is None:
            return None

        # 过滤目标用户
        if self.config.target_users and message.user_id not in self.config.target_users:
            return None

        # 加入处理队列
        await self._message_queue.put(message)
        self._message_count += 1
        self._last_message_time = time.time()

        return message

    def _parse_message(self, raw: dict) -> Optional[ChatMessage]:
        """将渠道原始消息转为标准 ChatMessage"""
        try:
            return ChatMessage(
                message_id=str(raw.get("message_id", raw.get("id", ""))),
                chat_id=str(raw.get("chat_id", self.config.chat_id)),
                user_id=str(raw.get("user_id", raw.get("sender_id", ""))),
                user_name=str(raw.get("user_name", raw.get("sender_name", "未知"))),
                content=str(raw.get("content", raw.get("text", ""))),
                timestamp=float(raw.get("timestamp", time.time())),
                is_group=bool(raw.get("is_group", True)),
                reply_to=str(raw.get("reply_to", "")) if raw.get("reply_to") else None,
            )
        except Exception as e:
            logger.warning(f"消息解析失败: {e}")
            return None

    async def _process_messages(self):
        """消息处理循环 —— 从队列中取出消息并处理"""
        while self.status == ListenerStatus.RUNNING:
            try:
                # 等待消息（1 秒超时，用于检查状态）
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0,
                )

                # 处理消息
                await self._handle_message(message)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"消息处理异常: {e}")
                if self.on_error:
                    await self.on_error(e)

    async def _handle_message(self, message: ChatMessage):
        """处理单条消息"""
        # 调用外部回调
        if self.on_message:
            try:
                await self.on_message(message)
            except Exception as e:
                logger.warning(f"消息回调异常: {e}")

        # Q&A 提取（如果启用学习）
        if self.config.enable_learning and settings.ENABLE_AUTO_LEARNING:
            qa_pair = await qa_extractor.process_message(message)
            if qa_pair:
                self._qa_count += 1
                if self.on_qa_extracted:
                    try:
                        await self.on_qa_extracted(qa_pair)
                    except Exception as e:
                        logger.warning(f"Q&A 回调异常: {e}")

    def get_stats(self) -> dict:
        """获取监听器统计"""
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "agent_id": self.config.agent_id,
            "chat_name": self.config.chat_name,
            "status": self.status.value,
            "message_count": self._message_count,
            "qa_count": self._qa_count,
            "uptime_seconds": round(uptime),
            "last_message_time": self._last_message_time,
        }


class ListenerManager:
    """
    监听器管理器 —— 管理所有 Agent 的监听器

    Usage:
        manager = ListenerManager()

        # 为 Agent 添加监听
        await manager.add_listener(agent_id, config)

        # 启动所有监听器
        await manager.start_all()

        # 停止所有监听器
        await manager.stop_all()
    """

    def __init__(self):
        # agent_id:chat_id → listener
        self._listeners: dict[str, MessageListener] = {}

    def _make_key(self, agent_id: int, chat_id: str) -> str:
        return f"{agent_id}:{chat_id}"

    async def add_listener(self, config: ListenerConfig) -> MessageListener:
        """添加监听器"""
        key = self._make_key(config.agent_id, config.chat_id)

        if key in self._listeners:
            logger.warning(f"监听器已存在: {key}")
            return self._listeners[key]

        listener = MessageListener(config)
        self._listeners[key] = listener

        return listener

    async def remove_listener(self, agent_id: int, chat_id: str):
        """移除监听器"""
        key = self._make_key(agent_id, chat_id)
        listener = self._listeners.pop(key, None)

        if listener:
            await listener.stop()

    async def start_listener(self, agent_id: int, chat_id: str):
        """启动指定监听器"""
        key = self._make_key(agent_id, chat_id)
        listener = self._listeners.get(key)
        if listener:
            await listener.start()

    async def stop_listener(self, agent_id: int, chat_id: str):
        """停止指定监听器"""
        key = self._make_key(agent_id, chat_id)
        listener = self._listeners.get(key)
        if listener:
            await listener.stop()

    async def start_all(self):
        """启动所有监听器"""
        for listener in self._listeners.values():
            await listener.start()

    async def stop_all(self):
        """停止所有监听器"""
        for listener in self._listeners.values():
            await listener.stop()

    def get_listener(self, agent_id: int, chat_id: str) -> Optional[MessageListener]:
        """获取指定监听器"""
        key = self._make_key(agent_id, chat_id)
        return self._listeners.get(key)

    def get_agent_listeners(self, agent_id: int) -> list[MessageListener]:
        """获取 Agent 的所有监听器"""
        return [
            l for key, l in self._listeners.items()
            if key.startswith(f"{agent_id}:")
        ]

    def get_all_stats(self) -> list[dict]:
        """获取所有监听器统计"""
        return [l.get_stats() for l in self._listeners.values()]


# 全局监听器管理器
listener_manager = ListenerManager()