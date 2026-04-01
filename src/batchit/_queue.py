"""asyncio.Queue draining with size/timeout flushing."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import TypeVar

T = TypeVar("T")

#: Put this sentinel into a queue to signal end of stream to :func:`drain_queue`.
STOP: object = object()


async def drain_queue(
    queue: asyncio.Queue[T],
    *,
    size: int | None = None,
    timeout: float | None = None,
    sentinel: object = STOP,
) -> AsyncGenerator[list[T], None]:
    """Drain an :class:`asyncio.Queue` into batches, flushing on size or timeout.

    Unlike :func:`async_batcher`, this reads directly from a :class:`~asyncio.Queue`
    rather than wrapping an async iterable — useful when producers push to a queue
    you do not control.

    Put *sentinel* (default: :data:`STOP`) into the queue to signal end of stream.
    The sentinel is consumed but never included in a batch.

    Args:
        queue: The queue to drain.
        size: Maximum number of items per batch.
        timeout: Maximum seconds to wait for the next item before flushing.
        sentinel: Object that signals end of stream.  Default: :data:`STOP`.

    Yields:
        Non-empty ``list[T]`` batches.

    Raises:
        ValueError: If neither *size* nor *timeout* is provided.

    Examples:
        >>> import asyncio
        >>> from batchit import drain_queue, STOP
        >>>
        >>> async def run():
        ...     q = asyncio.Queue()
        ...     for i in range(5):
        ...         await q.put(i)
        ...     await q.put(STOP)
        ...     return [b async for b in drain_queue(q, size=2)]
        >>> asyncio.run(run())
        [[0, 1], [2, 3], [4]]
    """
    if size is None and timeout is None:
        raise ValueError("At least one of 'size' or 'timeout' must be provided.")
    if size is not None and size < 1:
        raise ValueError("'size' must be a positive integer.")
    if timeout is not None and timeout <= 0:
        raise ValueError("'timeout' must be a positive number.")

    buf: list[T] = []
    batch_deadline: float | None = None
    loop = asyncio.get_running_loop()

    while True:
        if timeout is not None and batch_deadline is not None:
            wait: float | None = batch_deadline - loop.time()
            if wait <= 0:
                if buf:
                    yield buf
                    buf = []
                batch_deadline = None
                continue
        else:
            wait = timeout

        try:
            item: object = await asyncio.wait_for(queue.get(), timeout=wait)
        except asyncio.TimeoutError:
            if buf:
                yield buf
                buf = []
            batch_deadline = None
            continue

        if item is sentinel:
            if buf:
                yield buf
            break

        if not buf and timeout is not None:
            batch_deadline = loop.time() + timeout

        buf.append(item)  # type: ignore[arg-type]

        if size is not None and len(buf) >= size:
            yield buf
            buf = []
            batch_deadline = None
