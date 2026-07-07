"""
智答引擎（ZhiDa Engine）—— Single-Flight 幂等控制

合并相同请求，防止同一问题同时触发多次 LLM 调用。
基于 diskcache 实现进程级请求去重。

模块开关：settings.ENABLE_SINGLE_FLIGHT
"""

import asyncio
import hashlib
import threading
from typing import Optional, Callable, Awaitable, Any
from dataclasses import dataclass, field

from loguru import logger
from diskcache import Cache

from app.core.config import settings


@dataclass
class PendingRequest:
    """等待中的请求 —— 多个相同请求共享同一个 Future"""
    future: asyncio.Future = field(default_factory=asyncio.Future)
    created_at: float = field(default_factory=lambda: __import__("time").time())


class SingleFlight:
    """
    Single-Flight 请求合并 —— 相同请求只执行一次

    多个相同请求并发到达时，只有第一个真正执行，
    其余请求等待第一个完成并共享结果。

    通过模块开关 ENABLE_SINGLE_FLIGHT 控制是否启用。

    Usage:
        sf = SingleFlight(cache_dir=settings.cache_dir)

        async def do_query(question: str) -> str:
            return await llm_gateway.chat(question)

        # 使用 Single-Flight 包装
        result = await sf.do("query_key", do_query, "问题")
    """

    def __init__(self, cache_dir: str):
        self._cache = Cache(cache_dir)
        self._pending: dict[str, PendingRequest] = {}
        self._lock = threading.RLock()

    def _make_key(self, *args, **kwargs) -> str:
        """生成请求唯一键"""
        raw = str(args) + str(sorted(kwargs.items()))
        return hashlib.sha256(raw.encode()).hexdigest()

    async def do(
        self,
        key: str,
        fn: Callable[..., Awaitable[Any]],
        *args,
        **kwargs,
    ) -> Any:
        """
        执行请求 —— 如果启用 Single-Flight，相同 key 的请求合并

        Args:
            key: 请求唯一标识
            fn: 实际执行的异步函数
            *args, **kwargs: 传递给 fn 的参数

        Returns:
            fn 的执行结果
        """
        # 如果模块开关关闭，直接执行
        if not settings.ENABLE_SINGLE_FLIGHT:
            return await fn(*args, **kwargs)

        request_key = f"sf:{key}:{self._make_key(*args, **kwargs)}"

        # 检查是否有正在进行的相同请求
        with self._lock:
            if request_key in self._pending:
                pending = self._pending[request_key]
                logger.debug(f"Single-Flight 合并请求: {key}")
                # 等待第一个请求完成
                future = pending.future
            else:
                # 创建新的 pending 请求
                future = asyncio.Future()
                self._pending[request_key] = PendingRequest(future=future)

        # 如果 future 已存在（被合并的请求），等待结果
        if request_key in self._pending and self._pending[request_key].future is not future:
            # 等待第一个请求的结果
            try:
                return await future
            except Exception:
                # 如果第一个请求失败，自己也尝试执行
                pass

        # 第一个请求：执行实际逻辑
        try:
            result = await fn(*args, **kwargs)
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            # 清理 pending 状态
            with self._lock:
                self._pending.pop(request_key, None)

    async def do_with_disk_lock(
        self,
        key: str,
        fn: Callable[..., Awaitable[Any]],
        ttl: int = 60,
        *args,
        **kwargs,
    ) -> Any:
        """
        使用 diskcache 锁执行 —— 跨进程的 Single-Flight

        适用于可能被多个进程同时调用的场景（如文档解析）。

        Args:
            key: 请求唯一标识
            fn: 实际执行的异步函数
            ttl: 锁的过期时间（秒），防止死锁
            *args, **kwargs: 传递给 fn 的参数
        """
        if not settings.ENABLE_SINGLE_FLIGHT:
            return await fn(*args, **kwargs)

        lock_key = f"sf_lock:{key}"

        # 尝试获取锁
        acquired = self._cache.add(lock_key, "locked", expire=ttl)

        if not acquired:
            logger.debug(f"Single-Flight 跨进程合并: {key}")
            # 等待锁释放
            for _ in range(ttl * 10):  # 最多等待 TTL 秒
                if lock_key not in self._cache:
                    # 锁已释放，但结果可能已被缓存
                    return await fn(*args, **kwargs)
                await asyncio.sleep(0.1)

            # 超时，强制执行
            logger.warning(f"Single-Flight 锁超时: {key}，强制执行")

        try:
            return await fn(*args, **kwargs)
        finally:
            self._cache.delete(lock_key)


# 全局 Single-Flight 实例
single_flight = SingleFlight(cache_dir=settings.cache_dir)