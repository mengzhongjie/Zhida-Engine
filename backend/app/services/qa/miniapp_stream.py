"""小程序轮询式流输出：适配 CloudBase 会缓冲 HTTP/SSE 响应的限制。"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from loguru import logger


@dataclass
class MiniAppStreamJob:
    id: str
    owner_openid: str
    text: str = ""
    done: bool = False
    error: str = ""
    created_at: float = field(default_factory=time.monotonic)
    sources: list[dict] = field(default_factory=list)


class MiniAppStreamManager:
    """进程内短生命周期流任务，不依赖 Redis、WebSocket 或外部队列。"""

    def __init__(self):
        self._jobs: dict[str, MiniAppStreamJob] = {}

    def start(
        self,
        owner_openid: str,
        producer,
        on_complete: Callable[[MiniAppStreamJob], Awaitable[None]],
    ) -> MiniAppStreamJob:
        self._purge_expired()
        job = MiniAppStreamJob(id=uuid.uuid4().hex, owner_openid=owner_openid)
        self._jobs[job.id] = job

        async def run() -> None:
            try:
                async for chunk in producer:
                    job.text += chunk
                await on_complete(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(f"小程序流任务失败: {job.id}: {exc}")
                job.error = "回答生成失败，请稍后重试"
            finally:
                job.done = True

        asyncio.create_task(run(), name=f"miniapp-stream-{job.id}")
        return job

    def read(self, stream_id: str, owner_openid: str, cursor: int) -> dict:
        self._purge_expired()
        job = self._jobs.get(stream_id)
        if job is None or job.owner_openid != owner_openid:
            raise KeyError(stream_id)
        position = max(0, min(cursor, len(job.text)))
        return {
            "stream_id": job.id,
            "cursor": len(job.text),
            "delta": job.text[position:],
            "done": job.done,
            "error": job.error,
            "sources": job.sources if job.done else [],
        }

    def _purge_expired(self) -> None:
        cutoff = time.monotonic() - 15 * 60
        self._jobs = {key: job for key, job in self._jobs.items() if not (job.done and job.created_at < cutoff)}


miniapp_stream_manager = MiniAppStreamManager()
