"""Weighted batching — sync and async.

These tests simulate the primary motivation for max_weight: LLM token budgets,
byte-size API limits, and mixed-size payload batching.

Weight check is pre-append: if adding the next item would push the accumulated
weight over max_weight, the current batch is flushed first.  This guarantees
batches never exceed max_weight (except for a single item heavier than the budget,
which gets its own batch).
"""

from __future__ import annotations

import pytest

from batchit import async_batcher, batcher


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def token_count(text: str) -> float:
    """Rough token estimate: one token per word."""
    return float(len(text.split()))


# ---------------------------------------------------------------------------
# sync — max_weight
# ---------------------------------------------------------------------------

def test_weight_llm_token_budget():
    """Flush when cumulative token count would exceed the model's context window."""
    prompts = [
        "summarise this document",      # 3 tokens
        "translate to french",           # 3 tokens
        "what is the capital of france", # 6 tokens
        "ok",                            # 1 token
    ]
    # Budget of 7 tokens — pre-append check means no batch ever exceeds 7
    batches = list(batcher(prompts, max_weight=7, weight=token_count))
    assert sum(len(b) for b in batches) == len(prompts)
    assert [p for batch in batches for p in batch] == prompts
    for batch in batches:
        total = sum(token_count(p) for p in batch)
        # Pre-append guarantees budget adherence (single-item oversize is the only exception)
        assert total <= 7 or len(batch) == 1


def test_weight_byte_size_api_limit():
    """Flush when payload size (bytes) would exceed an API limit."""
    payloads = [b"x" * 100, b"x" * 200, b"x" * 150, b"x" * 50]
    batches = list(batcher(payloads, max_weight=300, weight=len))
    assert sum(len(b) for b in batches) == 4
    assert [item for batch in batches for item in batch] == payloads


def test_weight_with_size_whichever_first():
    """Both size and max_weight active — whichever fires first wins."""
    items = [1, 2, 3, 4, 5, 6]
    # size=3, max_weight=5 with weight=identity
    batches = list(batcher(items, size=3, max_weight=5, weight=float))
    assert [item for batch in batches for item in batch] == items
    for batch in batches:
        assert len(batch) <= 3


def test_weight_single_heavy_item():
    """An item heavier than max_weight gets its own batch — nothing is dropped."""
    items = [1, 100, 1]
    batches = list(batcher(items, max_weight=10, weight=float))
    assert [item for batch in batches for item in batch] == items
    # The heavy item (100) must be in its own batch
    assert any(batch == [100] for batch in batches)


def test_weight_exact_boundary():
    """Items that land exactly on max_weight do NOT trigger a flush until the next item."""
    # weight=10 per item, max_weight=30 → batches of exactly 3
    batches = list(batcher(range(9), max_weight=30, weight=lambda _: 10))
    assert batches == [[0, 1, 2], [3, 4, 5], [6, 7, 8]]


def test_weight_raises_if_max_weight_zero():
    with pytest.raises(ValueError):
        list(batcher(range(5), max_weight=0, weight=float))


def test_weight_raises_if_max_weight_negative():
    with pytest.raises(ValueError):
        list(batcher(range(5), max_weight=-1.0, weight=float))


def test_weight_requires_weight_callable():
    """max_weight without weight raises ValueError."""
    with pytest.raises(ValueError, match="together"):
        list(batcher(range(5), max_weight=10))


def test_weight_requires_max_weight():
    """weight without max_weight raises ValueError."""
    with pytest.raises(ValueError, match="together"):
        list(batcher(range(5), weight=float))


# ---------------------------------------------------------------------------
# sync — min_size
# ---------------------------------------------------------------------------

def test_min_size_prevents_small_timeout_batches():
    """Timeout does not flush until at least min_size items are buffered."""
    import time

    def slow_gen():
        for i in range(4):
            time.sleep(0.05)
            yield i

    # timeout=0.06 would normally fire after ~1 item; min_size=2 requires 2+
    batches = list(batcher(slow_gen(), timeout=0.06, min_size=2))
    for batch in batches[:-1]:  # last batch is "final" — may be smaller
        assert len(batch) >= 2


def test_min_size_does_not_affect_size_flush():
    """min_size does not gate size-triggered flushes."""
    batches = list(batcher(range(6), size=2, min_size=5))
    assert batches == [[0, 1], [2, 3], [4, 5]]


def test_min_size_final_batch_always_yielded():
    """Remaining items are always yielded even if below min_size."""
    batches = list(batcher(range(3), size=10, min_size=5))
    assert batches == [[0, 1, 2]]


# ---------------------------------------------------------------------------
# async — max_weight and min_size
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_weight_token_budget():
    """Async: flush on token budget — same pre-append semantics as sync."""
    prompts = [
        "summarise this document",
        "translate to french",
        "what is the capital of france",
        "ok",
    ]

    async def source():
        for p in prompts:
            yield p

    batches = [b async for b in async_batcher(source(), max_weight=7, weight=token_count)]
    assert sum(len(b) for b in batches) == len(prompts)
    assert [p for batch in batches for p in batch] == prompts
    for batch in batches:
        total = sum(token_count(p) for p in batch)
        assert total <= 7 or len(batch) == 1


@pytest.mark.asyncio
async def test_async_weight_and_size_combined():
    """Async: size and max_weight both active."""
    async def source():
        for i in range(6):
            yield i

    batches = [b async for b in async_batcher(source(), size=3, max_weight=5, weight=float)]
    assert [item for batch in batches for item in batch] == list(range(6))
    for batch in batches:
        assert len(batch) <= 3


@pytest.mark.asyncio
async def test_async_min_size_prevents_small_timeout_batches():
    """Async: timeout does not flush until min_size items buffered."""
    import asyncio

    async def slow_source():
        for i in range(4):
            await asyncio.sleep(0.05)
            yield i

    batches = [b async for b in async_batcher(slow_source(), timeout=0.06, min_size=2)]
    for batch in batches[:-1]:
        assert len(batch) >= 2
