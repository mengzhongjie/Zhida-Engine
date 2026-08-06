import asyncio

from app.services.qa.concurrency import QAStreamConcurrency


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
