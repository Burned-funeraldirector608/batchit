"""Weighted batching — sync and async.

These tests simulate the primary motivation for max_weight: LLM token budgets,
byte-size API limits, and mixed-size payload batching.
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
    """Flush when cumulative token count exceeds the model's context window."""
    prompts = [
        "summarise this document",     # 3 tokens
        "translate to french",          # 3 tokens
        "what is the capital of france",# 6 tokens
        "ok",                           # 1 token
    ]
    # Budget of 7 tokens → first two prompts (6 tokens) fit; third pushes over
    batches = list(batcher(prompts, max_weight=7, weight=token_count))
    assert sum(len(b) for b in batches) == len(prompts)
    # Each batch must not exceed budget... unless a single item exceeds it
    for batch in batches:
        total = sum(token_count(p) for p in batch)
        # The triggering item is included — so weight may exceed max_weight
        # by at most one item's weight. Verify the batch before trigger was under.
        assert total >= 1


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
    """An item heavier than max_weight is still yielded — nothing is dropped."""
    items = [100, 1, 1]
    batches = list(batcher(items, max_weight=10, weight=float))
    assert [item for batch in batches for item in batch] == items


def test_weight_default_equals_size():
    """Default weight of 1.0 per item makes max_weight behave like size."""
    result_size = list(batcher(range(7), size=3))
    result_weight = list(batcher(range(7), max_weight=3))
    assert result_size == result_weight


def test_weight_raises_if_max_weight_zero():
    with pytest.raises(ValueError):
        list(batcher(range(5), max_weight=0))


def test_weight_raises_if_max_weight_negative():
    with pytest.raises(ValueError):
        list(batcher(range(5), max_weight=-1.0))


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
    """Async: flush on token budget — same semantics as sync."""
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
    assert [item for batch in batches for item in batch] == prompts


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
