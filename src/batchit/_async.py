"""Asynchronous iterator batcher."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterable
from typing import TypeVar

T = TypeVar("T")

_DONE = object()  # sentinel pushed by the producer when the source is exhausted


async def async_batcher(
    aiterable: AsyncIterable[T],
    *,
    size: int | None = None,
    timeout: float | None = None,
) -> AsyncGenerator[list[T], None]:
    """Batch items from *aiterable*, flushing when *size* is reached OR *timeout*
    seconds have elapsed since the first item in the current batch arrived.

    Unlike the synchronous :func:`batcher`, the async variant spawns a small
    background task that drains the source into an internal queue.  The
    consumer side uses ``asyncio.wait_for`` on ``queue.get()``; when the
    timeout fires the queue consumer is cancelled — not the source generator —
    so no items are ever lost.

    At least one of *size* or *timeout* must be provided.

    Args:
        aiterable: Any async iterable to batch.
        size: Maximum number of items per batch.  ``None`` means no size limit.
        timeout: Maximum seconds to accumulate a batch (measured from the first
            item).  ``None`` means no time limit.

    Yields:
        Non-empty ``list`` of items.

    Raises:
        ValueError: If both *size* and *timeout* are ``None``.

    Examples:
        >>> import asyncio
        >>> async def run():
        ...     async def source():
        ...         for i in range(7):
        ...             yield i
        ...     return [b async for b in async_batcher(source(), size=3)]
        >>> asyncio.run(run())
        [[0, 1, 2], [3, 4, 5], [6]]
    """
    if size is None and timeout is None:
        raise ValueError("At least one of 'size' or 'timeout' must be provided.")
    if size is not None and size < 1:
        raise ValueError("'size' must be a positive integer.")
    if timeout is not None and timeout <= 0:
        raise ValueError("'timeout' must be a positive number.")

    queue: asyncio.Queue[object] = asyncio.Queue()

    async def _producer() -> None:
        try:
            async for item in aiterable:
                await queue.put(item)
        finally:
            await queue.put(_DONE)

    task = asyncio.create_task(_producer())
    buf: list[T] = []
    batch_deadline: float | None = None
    loop = asyncio.get_running_loop()

    try:
        while True:
            # How long to wait for the next queue item.
            if timeout is not None and batch_deadline is not None:
                wait: float | None = batch_deadline - loop.time()
                if wait <= 0:
                    # Deadline already passed — flush without blocking.
                    if buf:
                        yield buf
                        buf = []
                    batch_deadline = None
                    continue
            else:
                wait = timeout  # None (no limit) or full window for a new batch

            try:
                item = await asyncio.wait_for(queue.get(), timeout=wait)
            except asyncio.TimeoutError:
                if buf:
                    yield buf
                    buf = []
                batch_deadline = None
                continue

            if item is _DONE:
                if buf:
                    yield buf
                break

            # First item of a new batch — record deadline.
            if not buf and timeout is not None:
                batch_deadline = loop.time() + timeout

            buf.append(item)  # type: ignore[arg-type]

            if size is not None and len(buf) >= size:
                yield buf
                buf = []
                batch_deadline = None

    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
