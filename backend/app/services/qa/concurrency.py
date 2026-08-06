"""单机流式问答的全局并发闸门。"""

import asyncio
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class QueueAdmission:
    acquired: bool
    queued: bool


class QAStreamConcurrency:
    """限制同时执行的模型流，等待者保留在轻量 asyncio 队列中。"""

    def __init__(self) -> None:
        self._limit = max(1, settings.QA_MAX_CONCURRENT_STREAMS)
        self._semaphore = asyncio.Semaphore(self._limit)

    def is_saturated(self) -> bool:
        return self._semaphore.locked()

    async def acquire(self) -> QueueAdmission:
        queued = self.is_saturated()
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=max(1, settings.QA_STREAM_QUEUE_TIMEOUT_SECONDS),
            )
            return QueueAdmission(acquired=True, queued=queued)
        except TimeoutError:
            return QueueAdmission(acquired=False, queued=queued)

    def release(self) -> None:
        self._semaphore.release()


qa_stream_concurrency = QAStreamConcurrency()
