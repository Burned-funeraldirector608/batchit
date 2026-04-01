"""Weighted batching — sync and async.

These tests cover the ``max_weight`` / ``weight`` parameters added to both
``batcher`` and ``async_batcher``.  Weighted batching lets you flush based on
the total *size* of items in a batch rather than just their count — useful
whenever items are variable in size and a downstream system has a payload or
capacity limit.

Primary use cases covered here:
- LLM APIs with token-per-request limits
- HTTP APIs with byte-size body limits
- Variable-size database rows with a per-transaction byte budget
"""

import asyncio

import pytest

from batchit import async_batcher, batcher


# ---------------------------------------------------------------------------
# LLM token limits (the primary motivating use case)
# ---------------------------------------------------------------------------

def test_llm_token_limit():
    """Flush when the total token count in a batch would exceed the API limit.

    A real LLM embedding API (e.g. OpenAI text-embedding-3-small) accepts up
    to 8191 tokens per request.  Prompts vary wildly in length; batching by
    count alone either wastes capacity or overflows the limit.
    """
    prompts = [
        ("What is the capital of France?", 8),
        ("Explain quantum entanglement in simple terms.", 8),
        ("Write a haiku about autumn leaves.", 7),
        ("Summarise the French Revolution in one paragraph.", 9),
        ("What are the main causes of climate change?", 9),
    ]
    # max_weight=20 tokens per batch
    batches = list(
        batcher(prompts, max_weight=20, weight=lambda p: p[1])
    )

    # Check nothing is dropped
    assert [p for batch in batches for p in batch] == prompts
    # Check each batch stays within the token budget
    for batch in batches:
        assert sum(p[1] for p in batch) <= 20


def test_llm_single_heavy_prompt_gets_its_own_batch():
    """A prompt heavier than max_weight is flushed before the heavy item arrives,
    so the heavy item starts a fresh batch alone.

    We cannot split a prompt, so it occupies its own batch even if its weight
    alone exceeds max_weight.
    """
    prompts = [
        ("short", 5),
        ("an extremely long context window prompt", 30),  # heavier than max_weight=20
        ("another short one", 4),
    ]
    batches = list(batcher(prompts, max_weight=20, weight=lambda p: p[1]))

    assert [p for batch in batches for p in batch] == prompts
    # Each prompt ends up in its own batch: "short" is flushed before the heavy
    # item arrives; "another short one" is flushed before it too.
    assert len(batches) == 3
    assert batches[1] == [("an extremely long context window prompt", 30)]


def test_llm_all_prompts_fit_in_one_batch():
    """When total weight is below max_weight, a single batch is yielded."""
    prompts = [("prompt A", 10), ("prompt B", 8)]
    batches = list(batcher(prompts, max_weight=100, weight=lambda p: p[1]))
    assert len(batches) == 1
    assert batches[0] == prompts


# ---------------------------------------------------------------------------
# HTTP API byte-size limits
# ---------------------------------------------------------------------------

def test_http_payload_size_limit():
    """Flush when the total serialised payload would exceed a byte limit.

    Many HTTP bulk-ingest APIs enforce a maximum body size (e.g. 1 MB).
    """
    # Each record is a dict; use len(str(record)) as a rough byte estimate
    records = [{"id": i, "data": "x" * (i * 10)} for i in range(1, 8)]
    byte_sizes = [len(str(r)) for r in records]

    batches = list(batcher(records, max_weight=150, weight=lambda r: len(str(r))))

    assert [r for batch in batches for r in batch] == records
    for batch in batches[:-1]:  # last batch may be partial
        assert sum(len(str(r)) for r in batch) <= 150 + max(byte_sizes)


def test_http_exact_boundary():
    """Batch flushes exactly when the weight boundary is crossed."""
    # Items of weight 10; max_weight=30 → batches of exactly 3
    items = list(range(9))
    batches = list(batcher(items, max_weight=30, weight=lambda _: 10))
    assert batches == [[0, 1, 2], [3, 4, 5], [6, 7, 8]]


# ---------------------------------------------------------------------------
# weight + size together
# ---------------------------------------------------------------------------

def test_size_fires_before_weight():
    """When size is hit before max_weight, size drives the flush."""
    # Items of weight 1; max_weight=100 would never fire before size=3
    batches = list(batcher(range(9), size=3, max_weight=100, weight=lambda _: 1))
    assert batches == [[0, 1, 2], [3, 4, 5], [6, 7, 8]]


def test_weight_fires_before_size():
    """When max_weight is hit before size, weight drives the flush."""
    # Items of weight 5; max_weight=10 fires after 2 items; size=100 never fires
    batches = list(batcher(range(6), size=100, max_weight=10, weight=lambda _: 5))
    assert batches == [[0, 1], [2, 3], [4, 5]]


# ---------------------------------------------------------------------------
# weight + timeout together
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_weight_fires_before_timeout():
    """max_weight fires before the timeout window expires."""
    async def source():
        for i in range(6):
            yield i

    batches = [
        b async for b in async_batcher(
            source(), max_weight=10, weight=lambda _: 5, timeout=10.0
        )
    ]
    assert batches == [[0, 1], [2, 3], [4, 5]]


@pytest.mark.asyncio
async def test_async_timeout_fires_before_weight():
    """Timeout fires when items arrive too slowly to fill the weight budget."""
    async def slow_source():
        for i in range(4):
            await asyncio.sleep(0.08)
            yield i

    batches = [
        b async for b in async_batcher(
            slow_source(), max_weight=1000, weight=lambda _: 1, timeout=0.1
        )
    ]
    # Items arrive slower than the timeout, so small batches are flushed
    assert sum(len(b) for b in batches) == 4
    assert len(batches) >= 2


# ---------------------------------------------------------------------------
# async weighted batching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_llm_token_limit():
    """Async variant respects token budget, nothing dropped."""
    async def prompt_stream():
        for prompt, tokens in [("a", 8), ("b", 8), ("c", 7), ("d", 9), ("e", 9)]:
            yield (prompt, tokens)

    batches = [
        b async for b in async_batcher(
            prompt_stream(), max_weight=20, weight=lambda p: p[1]
        )
    ]
    all_prompts = [p for batch in batches for p in batch]
    assert len(all_prompts) == 5
    for batch in batches:
        assert sum(p[1] for p in batch) <= 20


@pytest.mark.asyncio
async def test_async_weight_nothing_dropped():
    """All items reach exactly one batch — no silent drops."""
    source_items = list(range(1, 11))  # weights 1..10

    async def source():
        for i in source_items:
            yield i

    batches = [
        b async for b in async_batcher(source(), max_weight=15, weight=lambda x: x)
    ]
    assert [i for batch in batches for i in batch] == source_items


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def test_max_weight_requires_weight():
    with pytest.raises(ValueError, match="together"):
        list(batcher(range(5), max_weight=10))


def test_weight_requires_max_weight():
    with pytest.raises(ValueError, match="together"):
        list(batcher(range(5), weight=lambda x: x))


def test_max_weight_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        list(batcher(range(5), max_weight=0, weight=lambda x: x))


def test_no_args_error_mentions_max_weight():
    """Error message should name all three parameters."""
    with pytest.raises(ValueError, match="max_weight"):
        list(batcher(range(5)))


@pytest.mark.asyncio
async def test_async_max_weight_requires_weight():
    with pytest.raises(ValueError, match="together"):
        async for _ in async_batcher(
            (x async for x in _agen(range(5))), max_weight=10
        ):
            pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _agen(items):
    for item in items:
        yield item
