"""Tests for batchit.async_batcher (asynchronous)."""

import asyncio

import pytest

from batchit import async_batcher


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def agen(items):
    """Simple async generator from a list."""
    for item in items:
        yield item


async def slow_agen(items, delay):
    """Async generator with a sleep between items."""
    for item in items:
        await asyncio.sleep(delay)
        yield item


async def collect(aiterable):
    return [batch async for batch in aiterable]


# ---------------------------------------------------------------------------
# size only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_size_exact_multiple():
    result = await collect(async_batcher(agen(range(6)), size=2))
    assert result == [[0, 1], [2, 3], [4, 5]]


@pytest.mark.asyncio
async def test_size_with_remainder():
    result = await collect(async_batcher(agen(range(7)), size=3))
    assert result == [[0, 1, 2], [3, 4, 5], [6]]


@pytest.mark.asyncio
async def test_size_empty_iterable():
    result = await collect(async_batcher(agen([]), size=5))
    assert result == []


@pytest.mark.asyncio
async def test_size_larger_than_input():
    result = await collect(async_batcher(agen(range(3)), size=100))
    assert result == [[0, 1, 2]]


# ---------------------------------------------------------------------------
# timeout only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_flushes_mid_stream():
    # Items arrive every 0.06 s; timeout = 0.1 s → multiple flushes
    result = await collect(async_batcher(slow_agen(range(4), 0.06), timeout=0.1))
    assert sum(len(b) for b in result) == 4
    assert len(result) >= 2


@pytest.mark.asyncio
async def test_timeout_real_flush_no_items():
    """Timeout fires even when source pauses — key async advantage."""
    async def pausing_gen():
        yield 1
        await asyncio.sleep(0.2)   # pause longer than timeout
        yield 2

    result = await collect(async_batcher(pausing_gen(), timeout=0.05))
    # First item flushed by timeout; second item as remainder
    assert result == [[1], [2]]


@pytest.mark.asyncio
async def test_timeout_no_flush_needed():
    result = await collect(async_batcher(agen(range(5)), timeout=5.0))
    assert result == [[0, 1, 2, 3, 4]]


# ---------------------------------------------------------------------------
# size + timeout together
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_size_fires_before_timeout():
    result = await collect(async_batcher(agen(range(6)), size=2, timeout=10.0))
    assert result == [[0, 1], [2, 3], [4, 5]]


@pytest.mark.asyncio
async def test_timeout_fires_before_size():
    result = await collect(async_batcher(slow_agen(range(4), 0.06), size=100, timeout=0.1))
    assert sum(len(b) for b in result) == 4
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raises_if_no_args():
    with pytest.raises(ValueError, match="At least one"):
        async for _ in async_batcher(agen(range(5))):
            pass


@pytest.mark.asyncio
async def test_raises_if_size_zero():
    with pytest.raises(ValueError):
        async for _ in async_batcher(agen(range(5)), size=0):
            pass


@pytest.mark.asyncio
async def test_raises_if_timeout_zero():
    with pytest.raises(ValueError):
        async for _ in async_batcher(agen(range(5)), timeout=0):
            pass


@pytest.mark.asyncio
async def test_items_not_dropped():
    source = list(range(17))
    batches = await collect(async_batcher(agen(source), size=5))
    assert [item for batch in batches for item in batch] == source


# ---------------------------------------------------------------------------
# real-world patterns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kafka_like_consumer():
    """Burst of items, then a long pause, then more — simulates an async Kafka consumer.

    Unlike the sync batcher, the async variant uses asyncio.wait_for internally,
    so the timeout fires even while the source is stalled between polls.
    """
    async def kafka_consumer():
        for i in range(3):              # fast burst
            yield i
        await asyncio.sleep(0.2)        # simulated poll interval (broker quiet)
        for i in range(3, 5):           # second burst
            yield i

    result = await collect(async_batcher(kafka_consumer(), size=10, timeout=0.1))
    assert result == [[0, 1, 2], [3, 4]]


@pytest.mark.asyncio
async def test_multiple_consecutive_timeout_flushes():
    """Each slow item becomes its own batch — verifies per-flush state reset."""
    result = await collect(async_batcher(slow_agen(range(5), 0.1), timeout=0.05))
    assert sum(len(b) for b in result) == 5
    assert len(result) >= 3


@pytest.mark.asyncio
async def test_source_exception_propagates():
    """An exception raised by the async source propagates out of async_batcher."""
    async def broken_gen():
        yield 1
        yield 2
        raise RuntimeError("async source failed")

    with pytest.raises(RuntimeError, match="async source failed"):
        await collect(async_batcher(broken_gen(), size=10))


@pytest.mark.asyncio
async def test_cancellation_does_not_hang():
    """Breaking out of the async for loop mid-stream does not hang or leak tasks."""
    async def infinite_gen():
        i = 0
        while True:
            await asyncio.sleep(0.01)
            yield i
            i += 1

    async def consume_two():
        count = 0
        async for _ in async_batcher(infinite_gen(), size=2):
            count += 1
            if count == 2:
                break

    await asyncio.wait_for(consume_two(), timeout=2.0)
