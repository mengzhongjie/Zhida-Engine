"""单机流式问答的全局并发闸门。"""

import asyncio
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class QueueAdmission:
    acquired: bool
    queued: bool
    queue_full: bool = False


class QAStreamConcurrency:
    """限制同时执行的模型流，等待者保留在轻量 asyncio 队列中。"""

    def __init__(self, limit: int | None = None, max_queue: int | None = None) -> None:
        self._limit = max(1, limit if limit is not None else settings.QA_MAX_CONCURRENT_STREAMS)
        self._max_queue = max(0, max_queue if max_queue is not None else settings.QA_MAX_STREAM_QUEUE)
        self._semaphore = asyncio.Semaphore(self._limit)
        self._admitted = 0
        self._admission_lock = asyncio.Lock()

    def is_saturated(self) -> bool:
        return self._semaphore.locked()

    async def acquire(self) -> QueueAdmission:
        # 限制“执行中 + 排队中”的总数。否则持有有效兑换码的攻击者可以
        # 用大量 SSE 等待连接耗尽单机内存、数据库会话和反向代理连接。
        async with self._admission_lock:
            if self._admitted >= self._limit + self._max_queue:
                return QueueAdmission(acquired=False, queued=True, queue_full=True)
            queued = self._admitted >= self._limit
            self._admitted += 1
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=max(1, settings.QA_STREAM_QUEUE_TIMEOUT_SECONDS),
            )
            return QueueAdmission(acquired=True, queued=queued)
        except TimeoutError:
            await self._leave_queue()
            return QueueAdmission(acquired=False, queued=queued)

        except BaseException:
            await self._leave_queue()
            raise

    async def _leave_queue(self) -> None:
        async with self._admission_lock:
            self._admitted = max(0, self._admitted - 1)

    async def release(self) -> None:
        await self._leave_queue()
        self._semaphore.release()


qa_stream_concurrency = QAStreamConcurrency()


class PerUserStreamGuard:
    """同一普通用户最多保留一条执行中或排队中的问答。"""

    def __init__(self) -> None:
        self._owners: set[int] = set()
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: int) -> bool:
        async with self._lock:
            if user_id in self._owners:
                return False
            self._owners.add(user_id)
            return True

    async def release(self, user_id: int) -> None:
        async with self._lock:
            self._owners.discard(user_id)


per_user_stream_guard = PerUserStreamGuard()
