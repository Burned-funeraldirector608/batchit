"""Synchronous iterator batcher."""

from __future__ import annotations

import time
from collections.abc import Callable, Generator, Iterable
from typing import TypeVar

T = TypeVar("T")


def batcher(
    iterable: Iterable[T],
    *,
    size: int | None = None,
    timeout: float | None = None,
    max_weight: float | None = None,
    weight: Callable[[T], float] | None = None,
) -> Generator[list[T], None, None]:
    """Batch items from *iterable*, flushing when *size* is reached, *timeout*
    seconds have elapsed since the first item in the current batch arrived, or
    the accumulated ``weight(item)`` sum reaches *max_weight* — whichever fires
    first.

    At least one of *size*, *timeout*, or *max_weight* must be provided.

    The timeout is measured from the moment the **first item** in a batch is
    received.  The check runs **after** each item is appended, so the item
    whose arrival reveals that the deadline has passed is included in the
    current (flushing) batch — not deferred to the next one.  No threads or
    background tasks are involved; this makes the function safe in any
    single-threaded context (Kafka consumers, DB cursors, file readers, etc.).

    The weight check runs **before** appending: if adding the incoming item
    would push the accumulated weight over *max_weight*, the current batch is
    flushed first and the item starts a new batch.  This guarantees that no
    batch exceeds *max_weight*, except when a single item is heavier than
    *max_weight* on its own (it cannot be split).

    Args:
        iterable: Any iterable to batch.
        size: Maximum number of items per batch.  ``None`` means no size limit.
        timeout: Maximum seconds to accumulate a batch.  ``None`` means no time
            limit.
        max_weight: Maximum total weight per batch.  ``None`` means no weight
            limit.  Must be provided together with *weight*.
        weight: Callable that returns the numeric weight of a single item.
            Required when *max_weight* is set.  Common uses: ``len`` for byte /
            character counts, ``lambda x: x.token_count`` for LLM token limits.

    Yields:
        Non-empty ``list`` of items.

    Raises:
        ValueError: If none of *size*, *timeout*, *max_weight* are provided, if
            *max_weight* is given without *weight* (or vice-versa), or if any
            numeric parameter is out of range.

    Examples:
        >>> list(batcher(range(7), size=3))
        [[0, 1, 2], [3, 4, 5], [6]]

        >>> list(batcher([1, 2, 3, 4, 5], max_weight=6, weight=lambda x: x))
        [[1, 2, 3], [4, 5]]

        >>> import time
        >>> def slow():
        ...     for i in range(4):
        ...         time.sleep(0.15)
        ...         yield i
        >>> list(batcher(slow(), size=10, timeout=0.25))
        [[0, 1], [2, 3]]
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
    if max_weight is not None and max_weight <= 0:
        raise ValueError("'max_weight' must be a positive number.")

    buf: list[T] = []
    batch_start: float | None = None
    accumulated_weight: float = 0.0

    for item in iterable:
        now = time.monotonic()
        item_weight = weight(item) if weight is not None else 0.0

        # Weight check runs BEFORE appending: if this item would push the batch
        # over max_weight, flush whatever is buffered first, then start fresh.
        # This guarantees no batch exceeds max_weight (except a single item that
        # is heavier than max_weight on its own — it cannot be split).
        if max_weight is not None and buf and accumulated_weight + item_weight > max_weight:
            yield buf
            buf = []
            batch_start = None
            accumulated_weight = 0.0

        if not buf:
            batch_start = now
        buf.append(item)
        accumulated_weight += item_weight

        full = size is not None and len(buf) >= size
        timed_out = timeout is not None and (now - batch_start) >= timeout  # type: ignore[operator]

        if full or timed_out:
            yield buf
            buf = []
            batch_start = None
            accumulated_weight = 0.0

    if buf:
        yield buf
