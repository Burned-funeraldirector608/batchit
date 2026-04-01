"""drain_queue — batching directly from asyncio.Queue.

Simulates producer/consumer patterns where items are pushed to a queue
by a separate coroutine and a consumer needs to process them in batches.
"""

from __future__ import annotations

import asyncio

import pytest

from batchit import STOP, drain_queue


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def fill_queue(queue: asyncio.Queue, items, *, delay: float = 0.0) -> None:
    """Push items into a queue, then signal STOP."""
    for item in items:
        if delay:
            await asyncio.sleep(delay)
        await queue.put(item)
    await queue.put(STOP)


# ---------------------------------------------------------------------------
# basic behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_size_batching():
    """Items are batched by count."""
    q: asyncio.Queue[int] = asyncio.Queue()
    asyncio.create_task(fill_queue(q, range(7)))
    batches = [b async for b in drain_queue(q, size=3)]
    assert batches == [[0, 1, 2], [3, 4, 5], [6]]


@pytest.mark.asyncio
async def test_empty_queue():
    """Immediate STOP yields no batches."""
    q: asyncio.Queue[int] = asyncio.Queue()
    await q.put(STOP)
    batches = [b async for b in drain_queue(q, size=10)]
    assert batches == []


@pytest.mark.asyncio
async def test_nothing_dropped():
    """All items reach a batch; none are silently lost."""
    q: asyncio.Queue[int] = asyncio.Queue()
    asyncio.create_task(fill_queue(q, range(23)))
    batches = [b async for b in drain_queue(q, size=5)]
    assert [item for batch in batches for item in batch] == list(range(23))


# ---------------------------------------------------------------------------
# timeout behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_flushes_on_slow_producer():
    """Timeout fires when the producer pauses longer than the window."""
    q: asyncio.Queue[int] = asyncio.Queue()
    asyncio.create_task(fill_queue(q, range(4), delay=0.08))
    batches = [b async for b in drain_queue(q, size=10, timeout=0.1)]
    assert sum(len(b) for b in batches) == 4
    assert len(batches) >= 2


@pytest.mark.asyncio
async def test_timeout_and_size_together():
    """Size and timeout both active — whichever fires first wins."""
    q: asyncio.Queue[int] = asyncio.Queue()
    asyncio.create_task(fill_queue(q, range(6)))
    batches = [b async for b in drain_queue(q, size=2, timeout=5.0)]
    assert batches == [[0, 1], [2, 3], [4, 5]]


# ---------------------------------------------------------------------------
# producer / consumer pattern
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_producer_consumer():
    """Producer and consumer run concurrently — typical real-world pattern."""
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=10)
    results: list[list[str]] = []

    async def producer():
        for i in range(10):
            await q.put(f"event-{i}")
            await asyncio.sleep(0)
        await q.put(STOP)

    async def consumer():
        async for batch in drain_queue(q, size=3, timeout=1.0):
            results.append(batch)

    await asyncio.gather(producer(), consumer())

    all_items = [item for batch in results for item in batch]
    assert all_items == [f"event-{i}" for i in range(10)]


# ---------------------------------------------------------------------------
# custom sentinel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_sentinel():
    """A user-defined sentinel signals end of stream."""
    q: asyncio.Queue = asyncio.Queue()
    END = "<<END>>"
    for i in range(4):
        await q.put(i)
    await q.put(END)

    batches = [b async for b in drain_queue(q, size=2, sentinel=END)]
    assert batches == [[0, 1], [2, 3]]


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raises_if_no_args():
    q: asyncio.Queue[int] = asyncio.Queue()
    with pytest.raises(ValueError, match="At least one"):
        async for _ in drain_queue(q):
            pass


@pytest.mark.asyncio
async def test_raises_if_size_zero():
    q: asyncio.Queue[int] = asyncio.Queue()
    with pytest.raises(ValueError):
        async for _ in drain_queue(q, size=0):
            pass


@pytest.mark.asyncio
async def test_raises_if_timeout_negative():
    q: asyncio.Queue[int] = asyncio.Queue()
    with pytest.raises(ValueError):
        async for _ in drain_queue(q, timeout=-1.0):
            pass
