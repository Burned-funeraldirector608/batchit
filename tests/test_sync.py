"""Tests for batchit.batcher (synchronous)."""

import time

import pytest

from batchit import batcher


# ---------------------------------------------------------------------------
# size only
# ---------------------------------------------------------------------------

def test_size_exact_multiple():
    result = list(batcher(range(6), size=2))
    assert result == [[0, 1], [2, 3], [4, 5]]


def test_size_with_remainder():
    result = list(batcher(range(7), size=3))
    assert result == [[0, 1, 2], [3, 4, 5], [6]]


def test_size_single_item_batches():
    result = list(batcher(range(3), size=1))
    assert result == [[0], [1], [2]]


def test_size_larger_than_input():
    result = list(batcher(range(3), size=100))
    assert result == [[0, 1, 2]]


def test_size_empty_iterable():
    result = list(batcher([], size=5))
    assert result == []


# ---------------------------------------------------------------------------
# timeout only
# ---------------------------------------------------------------------------

def slow_gen(items, delay):
    """Yield items with a delay between each."""
    for item in items:
        time.sleep(delay)
        yield item


def test_timeout_flushes_mid_stream():
    # Items arrive every 0.06 s; timeout = 0.1 s → flush after ~1-2 items
    result = list(batcher(slow_gen(range(4), 0.06), timeout=0.1))
    # Each batch should be small (1-2 items); total items preserved
    assert sum(len(b) for b in result) == 4
    assert all(len(b) >= 1 for b in result)
    # With 0.06 s delay and 0.1 s timeout, we expect multiple batches
    assert len(result) >= 2


def test_timeout_no_flush_needed():
    # Items arrive instantly; everything fits in one batch under the timeout
    result = list(batcher(range(5), timeout=5.0))
    assert result == [[0, 1, 2, 3, 4]]


def test_timeout_remainder_yielded():
    # Last few items should never be silently dropped
    result = list(batcher(slow_gen([1, 2, 3], 0.05), timeout=10.0))
    assert result == [[1, 2, 3]]


# ---------------------------------------------------------------------------
# size + timeout together
# ---------------------------------------------------------------------------

def test_size_fires_before_timeout():
    # Items arrive fast; size limit fires first
    result = list(batcher(range(6), size=2, timeout=10.0))
    assert result == [[0, 1], [2, 3], [4, 5]]


def test_timeout_fires_before_size():
    # Items arrive slowly; timeout fires before size=100 is reached
    result = list(batcher(slow_gen(range(4), 0.06), size=100, timeout=0.1))
    assert sum(len(b) for b in result) == 4
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# edge cases & validation
# ---------------------------------------------------------------------------

def test_raises_if_no_args():
    with pytest.raises(ValueError, match="At least one"):
        list(batcher(range(5)))


def test_raises_if_size_zero():
    with pytest.raises(ValueError):
        list(batcher(range(5), size=0))


def test_raises_if_timeout_zero():
    with pytest.raises(ValueError):
        list(batcher(range(5), timeout=0))


def test_raises_if_timeout_negative():
    with pytest.raises(ValueError):
        list(batcher(range(5), timeout=-1.0))


def test_items_not_dropped():
    source = list(range(17))
    batches = list(batcher(source, size=5))
    assert [item for batch in batches for item in batch] == source


def test_works_with_generator():
    def gen():
        yield from range(5)

    result = list(batcher(gen(), size=2))
    assert result == [[0, 1], [2, 3], [4]]


def test_works_with_non_int_items():
    data = ["a", "b", "c", "d"]
    result = list(batcher(data, size=2))
    assert result == [["a", "b"], ["c", "d"]]
