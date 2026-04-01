"""Asynchronous iterator batcher."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Callable
from typing import TypeVar

from batchit._sync import BatchResult, _default_weight, _validate

T = TypeVar("T")

_DONE = object()  # sentinel: source exhausted normally


class _Error:
    """Wraps an exception raised by the source so the consumer can re-raise it."""

    __slots__ = ("exc",)

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc


async def _async_batcher_impl(
    aiterable: AsyncIterable[T],
    *,
    size: int | None,
    timeout: float | None,
    max_weight: float | None,
    weight: Callable[[T], float],
    min_size: int,
    maxsize: int,
) -> AsyncGenerator[tuple[list[T], str, float], None]:
    """Core async batching loop. Yields (batch, reason, age) tuples."""
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
    current_weight = 0.0
    batch_deadline: float | None = None
    batch_start: float | None = None
    loop = asyncio.get_running_loop()

    try:
        while True:
            if timeout is not None and batch_deadline is not None:
                wait: float | None = batch_deadline - loop.time()
                if wait <= 0:
                    if buf and len(buf) >= min_size:
                        age = loop.time() - batch_start  # type: ignore[operator]
                        yield buf, "timeout", age
                        buf = []
                        current_weight = 0.0
                        batch_start = None
                    batch_deadline = None
                    continue
            else:
                wait = timeout

            try:
                item = await asyncio.wait_for(queue.get(), timeout=wait)
            except asyncio.TimeoutError:
                if buf and len(buf) >= min_size:
                    age = loop.time() - batch_start  # type: ignore[operator]
                    yield buf, "timeout", age
                    buf = []
                    current_weight = 0.0
                    batch_start = None
                batch_deadline = None
                continue

            if item is _DONE:
                if buf:
                    age = loop.time() - batch_start  # type: ignore[operator]
                    yield buf, "final", age
                break

            if isinstance(item, _Error):
                raise item.exc

            if not buf and timeout is not None:
                batch_deadline = loop.time() + timeout

            if not buf:
                batch_start = loop.time()

            buf.append(item)  # type: ignore[arg-type]
            current_weight += weight(item)  # type: ignore[arg-type]

            size_full = size is not None and len(buf) >= size
            weight_full = max_weight is not None and current_weight >= max_weight

            if size_full or weight_full:
                reason = "size" if size_full else "weight"
                age = loop.time() - batch_start  # type: ignore[operator]
                yield buf, reason, age
                buf = []
                current_weight = 0.0
                batch_start = None
                batch_deadline = None

    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def async_batcher(
    aiterable: AsyncIterable[T],
    *,
    size: int | None = None,
    timeout: float | None = None,
    max_weight: float | None = None,
    weight: Callable[[T], float] = _default_weight,
    min_size: int = 0,
    maxsize: int = 0,
) -> AsyncGenerator[list[T], None]:
    """Batch items from *aiterable*, flushing when *size*, *max_weight*, or *timeout* is reached.

    Spawns a background task to drain the source into an internal queue.
    Uses ``asyncio.wait_for`` so timeouts fire even when the source stalls.

    At least one of *size*, *timeout*, or *max_weight* must be provided.

    Args:
        aiterable: Any async iterable to batch.
        size: Maximum number of items per batch.
        timeout: Maximum seconds to accumulate a batch (measured from first item).
        max_weight: Maximum total weight per batch.  Requires *weight*.
        weight: Callable returning the weight of a single item.  Default: 1.0 per item.
        min_size: Minimum batch size before a timeout flush fires.
        maxsize: Internal queue cap for backpressure.  ``0`` = unbounded.

    Yields:
        Non-empty ``list`` of items.

    Raises:
        ValueError: If none of *size*, *timeout*, *max_weight* are provided.
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
    _validate(size, timeout, max_weight, min_size)
    if maxsize < 0:
        raise ValueError("'maxsize' must be a non-negative integer.")
    async for batch, _reason, _age in _async_batcher_impl(
        aiterable,
        size=size,
        timeout=timeout,
        max_weight=max_weight,
        weight=weight,
        min_size=min_size,
        maxsize=maxsize,
    ):
        yield batch


async def async_batcher_with_meta(
    aiterable: AsyncIterable[T],
    *,
    size: int | None = None,
    timeout: float | None = None,
    max_weight: float | None = None,
    weight: Callable[[T], float] = _default_weight,
    min_size: int = 0,
    maxsize: int = 0,
) -> AsyncGenerator[BatchResult[T], None]:
    """Like :func:`async_batcher` but yields :class:`BatchResult` objects with flush metadata.

    Args:
        aiterable: Any async iterable to batch.
        size: Maximum number of items per batch.
        timeout: Maximum seconds to accumulate a batch.
        max_weight: Maximum total weight per batch.
        weight: Callable returning the weight of a single item.
        min_size: Minimum batch size before a timeout flush fires.
        maxsize: Internal queue cap for backpressure.  ``0`` = unbounded.

    Yields:
        :class:`BatchResult` instances.
    """
    _validate(size, timeout, max_weight, min_size)
    if maxsize < 0:
        raise ValueError("'maxsize' must be a non-negative integer.")
    async for batch, reason, age in _async_batcher_impl(
        aiterable,
        size=size,
        timeout=timeout,
        max_weight=max_weight,
        weight=weight,
        min_size=min_size,
        maxsize=maxsize,
    ):
        yield BatchResult(items=batch, reason=reason, count=len(batch), age=age)  # type: ignore[arg-type]
