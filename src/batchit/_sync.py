"""Synchronous iterator batcher."""

from __future__ import annotations

import time
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

T = TypeVar("T")


@dataclass
class BatchResult(Generic[T]):
    """A batch paired with metadata about why and when it was flushed.

    Returned by :func:`batcher_with_meta` and :func:`async_batcher_with_meta`.
    """

    items: list[T]
    reason: Literal["size", "weight", "timeout", "final"]
    count: int
    age: float  # seconds elapsed since the first item in this batch arrived


def _validate(
    size: int | None,
    timeout: float | None,
    max_weight: float | None,
    weight: Callable | None,
    min_size: int,
) -> None:
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
    if min_size < 0:
        raise ValueError("'min_size' must be a non-negative integer.")


def _batcher_impl(
    iterable: Iterable[T],
    *,
    size: int | None,
    timeout: float | None,
    max_weight: float | None,
    weight: Callable[[T], float] | None,
    min_size: int,
) -> Generator[tuple[list[T], Literal["size", "weight", "timeout", "final"], float], None, None]:
    """Core batching loop. Yields (batch, reason, age) tuples."""
    buf: list[T] = []
    current_weight = 0.0
    batch_start: float | None = None

    for item in iterable:
        now = time.monotonic()

        # Weight check BEFORE appending — guarantees batches never exceed max_weight
        # (unless a single item is heavier than max_weight; it cannot be split).
        if max_weight is not None and weight is not None and buf:
            if current_weight + weight(item) > max_weight:  # type: ignore[arg-type]
                yield buf, "weight", now - batch_start  # type: ignore[operator]
                buf = []
                current_weight = 0.0
                batch_start = None

        if not buf:
            batch_start = now
        buf.append(item)  # type: ignore[arg-type]
        if weight is not None:
            current_weight += weight(item)  # type: ignore[arg-type]

        size_full = size is not None and len(buf) >= size
        timed_out = (
            timeout is not None
            and (now - batch_start) >= timeout  # type: ignore[operator]
            and len(buf) >= min_size
        )

        if size_full or timed_out:
            reason: Literal["size", "weight", "timeout", "final"] = (
                "size" if size_full else "timeout"
            )
            yield buf, reason, now - batch_start  # type: ignore[operator]
            buf = []
            current_weight = 0.0
            batch_start = None

    if buf:
        age = time.monotonic() - batch_start  # type: ignore[operator]
        yield buf, "final", age


def batcher(
    iterable: Iterable[T],
    *,
    size: int | None = None,
    timeout: float | None = None,
    max_weight: float | None = None,
    weight: Callable[[T], float] | None = None,
    min_size: int = 0,
) -> Generator[list[T], None, None]:
    """Batch items from *iterable*, flushing when *size*, *max_weight*, or *timeout* is reached.

    At least one of *size*, *timeout*, or *max_weight* must be provided.

    The weight check runs **before** appending each item: if the accumulated weight
    plus the incoming item's weight would exceed *max_weight*, the current batch is
    flushed first and the item starts a new batch.  This guarantees no batch exceeds
    *max_weight*, except when a single item is heavier than *max_weight* on its own
    (it cannot be split).

    The timeout is measured from the moment the **first item** in a batch is
    received.  The check runs **after** each item is appended, so the item whose
    arrival reveals that the deadline has passed is included in the current
    (flushing) batch.  No threads or background tasks are involved.

    Args:
        iterable: Any iterable to batch.
        size: Maximum number of items per batch.
        timeout: Maximum seconds to accumulate a batch (measured from first item).
        max_weight: Maximum total weight per batch.  Must be provided with *weight*.
        weight: Callable returning the weight of a single item.  Required with *max_weight*.
        min_size: Minimum batch size before a timeout flush is allowed.  Size and
            weight flushes always fire regardless.  Default: 0 (no minimum).

    Yields:
        Non-empty ``list`` of items.

    Raises:
        ValueError: If none of *size*, *timeout*, *max_weight* are provided, or if
            *max_weight* and *weight* are not provided together.

    Examples:
        >>> list(batcher(range(7), size=3))
        [[0, 1, 2], [3, 4, 5], [6]]

        >>> list(batcher([1, 2, 3, 4, 5], max_weight=6, weight=lambda x: x))
        [[1, 2, 3], [4, 5]]
    """
    _validate(size, timeout, max_weight, weight, min_size)
    for batch, _reason, _age in _batcher_impl(
        iterable,
        size=size,
        timeout=timeout,
        max_weight=max_weight,
        weight=weight,
        min_size=min_size,
    ):
        yield batch


def batcher_with_meta(
    iterable: Iterable[T],
    *,
    size: int | None = None,
    timeout: float | None = None,
    max_weight: float | None = None,
    weight: Callable[[T], float] | None = None,
    min_size: int = 0,
) -> Generator[BatchResult[T], None, None]:
    """Like :func:`batcher` but yields :class:`BatchResult` objects with flush metadata.

    Each result includes the items, the reason the batch was flushed
    (``"size"``, ``"weight"``, ``"timeout"``, or ``"final"``), the item count,
    and the age in seconds since the first item arrived.

    Args:
        iterable: Any iterable to batch.
        size: Maximum number of items per batch.
        timeout: Maximum seconds to accumulate a batch.
        max_weight: Maximum total weight per batch.  Must be provided with *weight*.
        weight: Callable returning the weight of a single item.  Required with *max_weight*.
        min_size: Minimum batch size before a timeout flush fires.

    Yields:
        :class:`BatchResult` instances.

    Examples:
        >>> results = list(batcher_with_meta(range(5), size=2))
        >>> results[0].reason
        'size'
        >>> results[-1].reason
        'final'
    """
    _validate(size, timeout, max_weight, weight, min_size)
    for batch, reason, age in _batcher_impl(
        iterable,
        size=size,
        timeout=timeout,
        max_weight=max_weight,
        weight=weight,
        min_size=min_size,
    ):
        yield BatchResult(items=batch, reason=reason, count=len(batch), age=age)


# ---------------------------------------------------------------------------
# Convenience aliases
# ---------------------------------------------------------------------------

def batch_by_size(iterable: Iterable[T], size: int) -> Generator[list[T], None, None]:
    """Batch *iterable* by item count only.  Shorthand for ``batcher(..., size=size)``."""
    return batcher(iterable, size=size)


def batch_by_timeout(iterable: Iterable[T], timeout: float) -> Generator[list[T], None, None]:
    """Batch *iterable* by elapsed time only.  Shorthand for ``batcher(..., timeout=timeout)``."""
    return batcher(iterable, timeout=timeout)
