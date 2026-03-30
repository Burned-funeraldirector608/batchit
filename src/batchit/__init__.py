"""batchit — batch any Python iterator by count and/or elapsed time.

Quick start::

    from batchit import batcher, async_batcher

    # Sync: flush every 100 items or every 5 seconds
    for batch in batcher(source, size=100, timeout=5.0):
        db.bulk_insert(batch)

    # Async: same, but works with async iterables
    async for batch in async_batcher(async_source, size=100, timeout=5.0):
        await db.bulk_insert(batch)
"""

from batchit._async import async_batcher
from batchit._sync import batcher

__all__ = ["batcher", "async_batcher"]
__version__ = "0.1.0"
