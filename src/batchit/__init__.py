"""batchit — batch any Python iterator by count, weight, and/or elapsed time.

Quick start::

    from batchit import batcher, async_batcher

    # Sync: flush every 100 items or every 5 seconds
    for batch in batcher(source, size=100, timeout=5.0):
        db.bulk_insert(batch)

    # Async: same, but works with async iterables
    async for batch in async_batcher(async_source, size=100, timeout=5.0):
        await db.bulk_insert(batch)

    # Weighted: flush when total tokens exceed 4096
    for batch in batcher(prompts, max_weight=4096, weight=count_tokens):
        llm.generate(batch)

    # Queue draining: batch from an asyncio.Queue
    async for batch in drain_queue(queue, size=50, timeout=2.0):
        await sink.write(batch)
"""

from batchit._async import async_batcher, async_batcher_with_meta
from batchit._queue import STOP, drain_queue
from batchit._sync import (
    BatchResult,
    batch_by_size,
    batch_by_timeout,
    batcher,
    batcher_with_meta,
)

__all__ = [
    # Core
    "batcher",
    "async_batcher",
    # Weighted / metadata variants
    "batcher_with_meta",
    "async_batcher_with_meta",
    "BatchResult",
    # Queue draining
    "drain_queue",
    "STOP",
    # Convenience aliases
    "batch_by_size",
    "batch_by_timeout",
]
__version__ = "0.4.0"
