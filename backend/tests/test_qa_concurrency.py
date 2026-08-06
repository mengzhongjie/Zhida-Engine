import asyncio

from app.services.qa.concurrency import QAStreamConcurrency, PerUserStreamGuard


def test_stream_queue_is_bounded_and_releases_slots():
    async def scenario():
        limiter = QAStreamConcurrency(limit=1, max_queue=1)

        first = await limiter.acquire()
        assert first.acquired and not first.queued

        second_task = asyncio.create_task(limiter.acquire())
        await asyncio.sleep(0)

        rejected = await limiter.acquire()
        assert not rejected.acquired
        assert rejected.queue_full

        await limiter.release()
        second = await second_task
        assert second.acquired and second.queued
        await limiter.release()

    asyncio.run(scenario())


def test_one_user_cannot_occupy_multiple_stream_slots():
    async def scenario():
        guard = PerUserStreamGuard()
        assert await guard.acquire(7)
        assert not await guard.acquire(7)
        assert await guard.acquire(8)
        await guard.release(7)
        assert await guard.acquire(7)

    asyncio.run(scenario())
