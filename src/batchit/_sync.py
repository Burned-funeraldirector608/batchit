"""Synchronous iterator batcher."""

from __future__ import annotations

import time
from collections.abc import Generator, Iterable
from typing import TypeVar

T = TypeVar("T")


def batcher(
    iterable: Iterable[T],
    *,
    size: int | None = None,
    timeout: float | None = None,
) -> Generator[list[T], None, None]:
    """Batch items from *iterable*, flushing when *size* is reached OR *timeout*
    seconds have elapsed since the first item in the current batch arrived.

    At least one of *size* or *timeout* must be provided.

    The timeout is measured from the moment the **first item** in a batch is
    received.  This means a slow upstream source naturally triggers time-based
    flushes without any threading or background tasks — making the function
    safe to use in any single-threaded context (Kafka consumers, DB cursors,
    file readers, etc.).

    Args:
        iterable: Any iterable to batch.
        size: Maximum number of items per batch.  ``None`` means no size limit.
        timeout: Maximum seconds to accumulate a batch.  ``None`` means no time
            limit.

    Yields:
        Non-empty ``list`` of items.

    Raises:
        ValueError: If both *size* and *timeout* are ``None``.

    Examples:
        >>> list(batcher(range(7), size=3))
        [[0, 1, 2], [3, 4, 5], [6]]

        >>> import time
        >>> def slow():
        ...     for i in range(4):
        ...         time.sleep(0.15)
        ...         yield i
        >>> list(batcher(slow(), size=10, timeout=0.25))
        [[0, 1], [2, 3]]
    """
    if size is None and timeout is None:
        raise ValueError("At least one of 'size' or 'timeout' must be provided.")
    if size is not None and size < 1:
        raise ValueError("'size' must be a positive integer.")
    if timeout is not None and timeout <= 0:
        raise ValueError("'timeout' must be a positive number.")

    buf: list[T] = []
    batch_start: float | None = None

    for item in iterable:
        now = time.monotonic()
        if not buf:
            batch_start = now
        buf.append(item)

        full = size is not None and len(buf) >= size
        timed_out = timeout is not None and (now - batch_start) >= timeout  # type: ignore[operator]

        if full or timed_out:
            yield buf
            buf = []
            batch_start = None

    if buf:
        yield buf
