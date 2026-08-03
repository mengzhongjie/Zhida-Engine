"""仅用于问答的进程内请求合并，避免并发重复消耗模型额度。"""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from loguru import logger

T = TypeVar("T")


class QARequestCoalescer:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def make_key(**payload: Any) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def run(self, key: str, operation: Callable[[], Awaitable[T]]) -> T:
        """相同的进行中问答共享同一个 Task；完成后立即移除，不取代持久化缓存。"""
        async with self._lock:
            task = self._tasks.get(key)
            if task is None:
                task = asyncio.create_task(operation(), name=f"qa-request-{key[:12]}")
                self._tasks[key] = task
                task.add_done_callback(lambda finished: self._tasks.pop(key, None))
            else:
                logger.info(f"合并重复问答请求: {key[:12]}")
        return await task


qa_request_coalescer = QARequestCoalescer()
