"""Asynchronous iterator batcher."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Callable
from typing import TypeVar

T = TypeVar("T")

_DONE = object()  # sentinel: source exhausted normally


class _Error:
    """Wraps an exception raised by the source so the consumer can re-raise it."""

    __slots__ = ("exc",)

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc


async def async_batcher(
    aiterable: AsyncIterable[T],
    *,
    size: int | None = None,
    timeout: float | None = None,
    maxsize: int = 0,
    max_weight: float | None = None,
    weight: Callable[[T], float] | None = None,
) -> AsyncGenerator[list[T], None]:
    """Batch items from *aiterable*, flushing when *size* is reached, *timeout*
    seconds have elapsed since the first item in the current batch arrived, or
    the accumulated ``weight(item)`` sum reaches *max_weight* — whichever fires
    first.

    Unlike the synchronous :func:`batcher`, the async variant spawns a small
    background task that drains the source into an internal queue.  The
    consumer side uses ``asyncio.wait_for`` on ``queue.get()``; when the
    timeout fires the queue consumer is cancelled — not the source generator —
    so no items are ever lost.

    At least one of *size*, *timeout*, or *max_weight* must be provided.

    The weight check runs **before** appending, matching the semantics of the
    synchronous :func:`batcher` — no batch will exceed *max_weight* except
    when a single item is heavier than *max_weight* on its own.

    Args:
        aiterable: Any async iterable to batch.
        size: Maximum number of items per batch.  ``None`` means no size limit.
        timeout: Maximum seconds to accumulate a batch (measured from the first
            item).  ``None`` means no time limit.
        maxsize: Maximum number of items to buffer in the internal queue before
            the producer blocks.  ``0`` (default) means unbounded.  Set this to
            apply backpressure when the source can outpace the consumer.
        max_weight: Maximum total weight per batch.  ``None`` means no weight
            limit.  Must be provided together with *weight*.
        weight: Callable that returns the numeric weight of a single item.
            Required when *max_weight* is set.

    Yields:
        Non-empty ``list`` of items.

    Raises:
        ValueError: If none of *size*, *timeout*, *max_weight* are provided, if
            *maxsize* is negative, or if *max_weight* / *weight* are not paired.
        Exception: Any exception raised by the source is re-raised by the consumer.

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
    if (max_weight is None) != (weight is None):
        raise ValueError("'max_weight' and 'weight' must be provided together.")
    if size is None and timeout is None and max_weight is None:
        raise ValueError(
            "At least one of 'size', 'timeout', or 'max_weight' must be provided."
        )
    if size is not None and size < 1:
        raise ValueError("'size' must be a positive integer.")
    if timeout is not None and timeout <= 0:
        raise ValueError("'timeout' must be a positive number.")
    if maxsize < 0:
        raise ValueError("'maxsize' must be a non-negative integer.")
    if max_weight is not None and max_weight <= 0:
        raise ValueError("'max_weight' must be a positive number.")

    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)

    async def _producer() -> None:
        try:
            async for item in aiterable:
                await queue.put(item)
            await queue.put(_DONE)
        except Exception as exc:
            await queue.put(_Error(exc))

    task = asyncio.create_task(_producer())
    buf: list[T] = []
    batch_deadline: float | None = None
    accumulated_weight: float = 0.0
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
                        accumulated_weight = 0.0
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
                    accumulated_weight = 0.0
                batch_deadline = None
                continue

            if item is _DONE:
                if buf:
                    yield buf
                break

            if isinstance(item, _Error):
                raise item.exc

            item_weight = weight(item) if weight is not None else 0.0  # type: ignore[arg-type]

            # Weight check runs BEFORE appending (same semantics as sync batcher).
            if max_weight is not None and buf and accumulated_weight + item_weight > max_weight:
                yield buf
                buf = []
                accumulated_weight = 0.0
                batch_deadline = None

            # First item of a new batch after a weight flush — record deadline.
            if not buf and timeout is not None:
                batch_deadline = loop.time() + timeout

            buf.append(item)  # type: ignore[arg-type]
            accumulated_weight += item_weight

            if size is not None and len(buf) >= size:
                yield buf
                buf = []
                accumulated_weight = 0.0
                batch_deadline = None

    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
