"""
智答引擎（ZhiDa Engine）—— 降级管理器

当依赖服务不可用时，自动降级而非直接报错，优先保证可用性。

降级策略：
1. LLM 降级：主模型不可用 → 已配置的云端降级模型 → 预设回复
2. 检索降级：混合检索不可用 → 关键词检索 → 纯 LLM 回复
3. 文档解析降级：完整解析 → 纯文本提取 → 分页解析 → 跳过
4. Embedding 降级：云端 API 不可用 → 跳过向量化

每个降级策略通过模块开关控制是否启用。
"""

import time
from enum import Enum
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

from loguru import logger

from app.core.config import settings


class DegradationLevel(str, Enum):
    """降级等级"""
    FULL = "full"          # 完整功能
    DEGRADED = "degraded"  # 部分降级
    MINIMAL = "minimal"    # 最低可用
    OFFLINE = "offline"    # 完全离线


@dataclass
class DegradationEvent:
    """降级事件记录"""
    service: str           # 服务名称
    from_level: DegradationLevel
    to_level: DegradationLevel
    reason: str            # 降级原因
    timestamp: float = field(default_factory=time.time)


class DegradationManager:
    """
    降级管理器 —— 管理所有服务的降级状态

    核心原则：优先保证可用性，即使功能降级也比完全不可用强。

    Usage:
        dm = DegradationManager()

        # 注册降级策略
        result = await dm.execute_with_fallback(
            service="llm",
            primary=primary_fn,
            fallbacks=[fallback_fn1, fallback_fn2],
            offline_response="服务暂时不可用",
        )
    """

    def __init__(self):
        self._service_levels: dict[str, DegradationLevel] = {}
        self._events: list[DegradationEvent] = []
        self._max_events = 100  # 最多保留 100 条降级事件

    # ================================================================
    # 降级执行
    # ================================================================

    async def execute_with_fallback(
        self,
        service: str,
        primary: Callable,
        fallbacks: Optional[list[Callable]] = None,
        offline_response: Any = None,
        *args,
        **kwargs,
    ) -> Any:
        """
        执行带降级的操作 —— 主策略失败后依次尝试降级策略

        Args:
            service: 服务名称（如 "llm", "retrieval", "embedding"）
            primary: 主策略函数
            fallbacks: 降级策略函数列表（按优先级排序）
            offline_response: 所有策略都失败时的兜底返回
            *args, **kwargs: 传递给各策略函数的参数

        Returns:
            策略函数的返回值，或 offline_response
        """
        current_level = self._service_levels.get(service, DegradationLevel.FULL)

        # 尝试主策略
        try:
            result = await self._try_execute(primary, *args, **kwargs)
            self._update_level(service, DegradationLevel.FULL)
            return result
        except Exception as e:
            logger.warning(f"[{service}] 主策略失败: {e}，尝试降级")
            self._record_event(service, DegradationLevel.FULL, DegradationLevel.DEGRADED, str(e)[:200])

        # 依次尝试降级策略
        if fallbacks:
            for i, fallback in enumerate(fallbacks):
                try:
                    result = await self._try_execute(fallback, *args, **kwargs)
                    level = DegradationLevel.DEGRADED if i == 0 else DegradationLevel.MINIMAL
                    self._update_level(service, level)
                    logger.info(f"[{service}] 降级策略 {i+1} 成功，当前等级: {level.value}")
                    return result
                except Exception as e:
                    logger.warning(f"[{service}] 降级策略 {i+1} 失败: {e}")

        # 所有策略都失败，返回离线兜底
        self._update_level(service, DegradationLevel.OFFLINE)
        self._record_event(service, DegradationLevel.MINIMAL, DegradationLevel.OFFLINE, "所有策略均失败")

        logger.error(f"[{service}] 所有策略均失败，返回离线兜底")
        return offline_response

    async def _try_execute(self, fn: Callable, *args, **kwargs) -> Any:
        """尝试执行函数 —— 支持同步和异步"""
        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        else:
            return fn(*args, **kwargs)

    # ================================================================
    # 状态管理
    # ================================================================

    def _update_level(self, service: str, level: DegradationLevel):
        """更新服务降级等级"""
        old_level = self._service_levels.get(service, DegradationLevel.FULL)
        if old_level != level:
            self._service_levels[service] = level
            logger.info(f"[{service}] 降级等级变更: {old_level.value} → {level.value}")

    def _record_event(self, service: str, from_level: DegradationLevel, to_level: DegradationLevel, reason: str):
        """记录降级事件"""
        event = DegradationEvent(
            service=service,
            from_level=from_level,
            to_level=to_level,
            reason=reason,
        )
        self._events.append(event)

        # 限制事件数量
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    def get_level(self, service: str) -> DegradationLevel:
        """获取服务当前降级等级"""
        return self._service_levels.get(service, DegradationLevel.FULL)

    def get_all_levels(self) -> dict[str, str]:
        """获取所有服务的降级等级"""
        return {k: v.value for k, v in self._service_levels.items()}

    def get_events(self, limit: int = 20) -> list[dict]:
        """获取最近的降级事件"""
        events = self._events[-limit:]
        return [
            {
                "service": e.service,
                "from": e.from_level.value,
                "to": e.to_level.value,
                "reason": e.reason,
                "timestamp": e.timestamp,
            }
            for e in events
        ]

    def is_healthy(self, service: str) -> bool:
        """检查服务是否健康（未降级）"""
        return self.get_level(service) == DegradationLevel.FULL

    # ================================================================
    # 预设降级策略
    # ================================================================

    @staticmethod
    def get_llm_offline_response() -> str:
        """LLM 完全不可用时的兜底回复"""
        return (
            "抱歉，AI 助手暂时无法提供服务。\n\n"
            "可能的原因：\n"
            "1. 网络连接异常\n"
            "2. API 额度已用完\n"
            "3. 模型服务维护中\n\n"
            "请稍后重试，或检查设置中的 LLM 配置。"
        )

    @staticmethod
    def get_retrieval_offline_response(question: str) -> str:
        """检索不可用时的兜底回复"""
        return (
            f"关于「{question[:50]}」，我暂时无法检索相关知识。\n"
            "请确认知识库已上传文档，或稍后重试。"
        )


# 全局降级管理器实例
degradation_manager = DegradationManager()
