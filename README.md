# batchit

> Tiny batching for Python pipelines, streams, and agent workflows.

[![PyPI version](https://img.shields.io/pypi/v/batchit.svg?cacheSeconds=60)](https://pypi.org/project/batchit/)
[![Python versions](https://img.shields.io/pypi/pyversions/batchit.svg?cacheSeconds=60)](https://pypi.org/project/batchit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/Ahmedie-m/batchit/actions/workflows/ci.yml/badge.svg)](https://github.com/Ahmedie-m/batchit/actions/workflows/ci.yml)

Batch any Python iterator by **count**, **weight**, **elapsed time**, or any combination — in one `pip install`, with no dependencies.

```python
from batchit import batcher, async_batcher

# Sync — flush every 100 items or when the next item reveals 5 s have passed
for batch in batcher(source, size=100, timeout=5.0):
    db.bulk_insert(batch)

# Async — flush every 100 items or after 5 s of silence from the source
async for batch in async_batcher(source, size=100, timeout=5.0):
    await db.bulk_insert(batch)

# Weighted — flush when cumulative token count exceeds 4096
for batch in batcher(prompts, max_weight=4096, weight=count_tokens):
    llm.generate(batch)

# Queue draining — batch directly from an asyncio.Queue
from batchit import drain_queue, STOP
async for batch in drain_queue(queue, size=50, timeout=2.0):
    await sink.write(batch)
```

---

## AI / agent pipelines

```python
# Batch embedding requests before upserting to a vector store
async for batch in async_batcher(document_stream(), size=96, timeout=2.0):
    vectors = await embed(batch)
    await vector_store.upsert(vectors)

# Token-budget batching for LLM inference
for batch in batcher(prompts, max_weight=4096, weight=count_tokens):
    responses = llm.generate(batch)

# Batch agent tool outputs before writing to Postgres
async for batch in async_batcher(tool_result_stream(), size=50, timeout=1.0):
    await db.execute("INSERT INTO results ...", batch)

# Batch scraped records before bulk API submission
for batch in batcher(scraper.records(), size=200, timeout=10.0):
    api.bulk_submit(batch)

# Batch trace/log events before shipping to observability backend
async for batch in async_batcher(event_stream(), size=500, timeout=5.0, maxsize=1000):
    await telemetry.ingest(batch)

# Inspect why each batch flushed
from batchit import batcher_with_meta
for result in batcher_with_meta(source, size=100, timeout=5.0):
    print(result.reason, result.count, result.age)
    process(result.items)
```

---

## Why not just write this yourself?

You could — it's not a lot of code. But here's what you'd need to get right:

- **Sync and async** variants with consistent semantics
- **Partial final batch** always flushed, never silently dropped
- **Timeout measured correctly** from the first item in the batch, not wall clock
- **Async timeout fires independently** of item delivery (via `asyncio.wait_for`) — not just on arrival
- **Weight-based flushing** for token budgets, byte limits, or any custom metric
- **Queue draining** for producer/consumer patterns with `asyncio.Queue`
- **Flush metadata** (`reason`, `age`, `count`) for observability and adaptive logic
- **Backpressure** support via bounded internal queue
- **Exception propagation** from the source through to the consumer
- **PEP 561 typing** so your IDE and type checker understand the API
- **Tested** across Python 3.10–3.13

`pip install batchit` and move on.

---

## Why batchit?

`more-itertools.batched()` batches by count only. In real streaming workloads
(Kafka consumers, database cursors, API result streams) you also need a **time
window** and often a **weight limit**. Every team writes this boilerplate. `batchit` is the one-liner that replaces it.

| | Count limit | Weight limit | Time limit | Async | Queue drain | Backpressure | Dependencies |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `batchit` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | none |
| `more-itertools` | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | 1 |
| `toolz` | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | 1 |
| hand-rolled | maybe | maybe | maybe | maybe | maybe | maybe | — |

---

## Installation

```bash
pip install batchit
```

No runtime dependencies. Python 3.10–3.13. Fully typed (PEP 561).
Works with generators, Kafka consumers, database cursors, file readers, async queues, and any other iterable.

---

## Usage

### Sync — `batcher`

```python
from batchit import batcher

# By size only
for batch in batcher(range(1000), size=50):
    process(batch)

# By timeout only
for batch in batcher(kafka_consumer, timeout=5.0):
    send_to_api(batch)

# By both — whichever fires first
for batch in batcher(db_cursor, size=200, timeout=10.0):
    write_to_s3(batch)

# By weight — flush when token budget is exhausted
for batch in batcher(prompts, max_weight=4096, weight=count_tokens):
    llm.generate(batch)

# Combined weight + size + timeout
for batch in batcher(records, size=100, max_weight=1_000_000, weight=len, timeout=10.0):
    upload(batch)
```

### Sync with metadata — `batcher_with_meta`

```python
from batchit import batcher_with_meta

for result in batcher_with_meta(source, size=100, timeout=5.0):
    print(f"Flushed {result.count} items after {result.age:.2f}s (reason: {result.reason})")
    process(result.items)
```

`BatchResult` fields: `items`, `reason` (`"size"` | `"weight"` | `"timeout"` | `"final"`), `count`, `age`.

### Async — `async_batcher`

```python
from batchit import async_batcher

async for batch in async_batcher(async_source, size=100, timeout=5.0):
    await db.bulk_insert(batch)

# With backpressure — producer blocks if more than 200 items are queued
async for batch in async_batcher(fast_source, size=50, timeout=2.0, maxsize=200):
    await slow_downstream(batch)

# With weight limit
async for batch in async_batcher(prompt_stream(), max_weight=4096, weight=count_tokens):
    await llm.generate_batch(batch)
```

### Async with metadata — `async_batcher_with_meta`

```python
from batchit import async_batcher_with_meta

async for result in async_batcher_with_meta(source, size=100, timeout=5.0):
    metrics.record(result.reason, result.count, result.age)
    await process(result.items)
```

### Queue draining — `drain_queue`

```python
from batchit import drain_queue, STOP
import asyncio

queue: asyncio.Queue[str] = asyncio.Queue()

# Put STOP into the queue to signal end of stream
async for batch in drain_queue(queue, size=50, timeout=2.0):
    await sink.write(batch)

# Custom sentinel
async for batch in drain_queue(queue, size=50, sentinel="<<END>>"):
    await sink.write(batch)
```

### Convenience aliases

```python
from batchit import batch_by_size, batch_by_timeout

for batch in batch_by_size(records, 100):      # same as batcher(records, size=100)
    process(batch)

for batch in batch_by_timeout(stream, 5.0):   # same as batcher(stream, timeout=5.0)
    flush(batch)
```

---

## Timeout semantics

The two variants behave differently under a slow or stalled source:

| | `batcher` (sync) | `async_batcher` (async) |
|---|---|---|
| **How timeout fires** | Checked on each item arrival | Fires independently via `asyncio.wait_for` |
| **Stalled source** | Waits until the next item arrives, then flushes | Flushes after *T* seconds even with no new items |
| **Triggering item** | Included in the flushing batch | Starts the next batch |
| **Threading** | None — single-threaded safe | asyncio event loop only |
| **Source exception** | Propagates immediately | Propagates to consumer |

**Rule of thumb:** use `batcher` for sync iterables where the source drives timing. Use `async_batcher` when you need the timeout to fire independently of item delivery.

---

## API

### `batcher(iterable, *, size=None, timeout=None, max_weight=None, weight=..., min_size=0)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `iterable` | `Iterable[T]` | Any iterable to batch |
| `size` | `int \| None` | Max items per batch |
| `timeout` | `float \| None` | Max seconds per batch, measured from the first item |
| `max_weight` | `float \| None` | Max total weight per batch |
| `weight` | `Callable[[T], float]` | Weight function for each item. Default: `1.0` per item |
| `min_size` | `int` | Minimum items before a timeout flush fires. Default: `0` |

Yields `list[T]`. At least one of `size`, `timeout`, or `max_weight` must be provided.

### `batcher_with_meta(iterable, *, size=None, timeout=None, max_weight=None, weight=..., min_size=0)`

Same parameters as `batcher`. Yields `BatchResult[T]` with `.items`, `.reason`, `.count`, `.age`.

### `async_batcher(aiterable, *, size=None, timeout=None, max_weight=None, weight=..., min_size=0, maxsize=0)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `aiterable` | `AsyncIterable[T]` | Any async iterable to batch |
| `size` | `int \| None` | Max items per batch |
| `timeout` | `float \| None` | Max seconds per batch, measured from the first item |
| `max_weight` | `float \| None` | Max total weight per batch |
| `weight` | `Callable[[T], float]` | Weight function for each item. Default: `1.0` per item |
| `min_size` | `int` | Minimum items before a timeout flush fires. Default: `0` |
| `maxsize` | `int` | Internal queue cap for backpressure. `0` = unbounded |

Yields `list[T]` asynchronously.

### `async_batcher_with_meta(aiterable, *, size=None, timeout=None, max_weight=None, weight=..., min_size=0, maxsize=0)`

Same parameters as `async_batcher`. Yields `BatchResult[T]` asynchronously.

### `drain_queue(queue, *, size=None, timeout=None, sentinel=STOP)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `queue` | `asyncio.Queue[T]` | Queue to drain |
| `size` | `int \| None` | Max items per batch |
| `timeout` | `float \| None` | Max seconds to wait for the next item before flushing |
| `sentinel` | `object` | Value that signals end of stream. Default: `STOP` |

Yields `list[T]` asynchronously. At least one of `size` or `timeout` must be provided.

### `BatchResult[T]`

| Field | Type | Description |
|-------|------|-------------|
| `items` | `list[T]` | The batch contents |
| `reason` | `"size" \| "weight" \| "timeout" \| "final"` | Why the batch was flushed |
| `count` | `int` | Number of items (`len(items)`) |
| `age` | `float` | Seconds elapsed since the first item in this batch arrived |

---

## Patterns

### Kafka consumer

```python
from kafka import KafkaConsumer
from batchit import batcher

consumer = KafkaConsumer("events")
for batch in batcher(consumer, size=500, timeout=10.0):
    db.bulk_insert([msg.value for msg in batch])
    consumer.commit()
```

### Database cursor

```python
cursor.execute("SELECT * FROM events")
for batch in batcher(cursor, size=1000):
    warehouse.insert_many(batch)
```

### LLM token-budget batching

```python
from batchit import batcher

def count_tokens(text: str) -> float:
    return len(text.split())  # or use tiktoken

for batch in batcher(prompts, max_weight=4096, weight=count_tokens):
    responses = llm.generate(batch)
```

### LLM embedding pipeline

```python
from batchit import async_batcher

async for batch in async_batcher(document_stream(), size=96, timeout=2.0):
    response = await openai_client.embeddings.create(input=batch, model="...")
    await vector_db.upsert(response.data)
```

### Agent tool results to Postgres

```python
async for batch in async_batcher(tool_outputs(), size=50, timeout=1.0):
    await conn.executemany("INSERT INTO tool_results VALUES ($1, $2)", batch)
```

### Adaptive flushing with metadata

```python
from batchit import batcher_with_meta

for result in batcher_with_meta(source, size=100, timeout=5.0, max_weight=4096, weight=len):
    if result.reason == "timeout" and result.count < 10:
        metrics.increment("small_timeout_batch")
    process(result.items)
```

### Producer/consumer queue draining

```python
import asyncio
from batchit import drain_queue, STOP

queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)

async def producer():
    async for event in event_source():
        await queue.put(event)
    await queue.put(STOP)

async def consumer():
    async for batch in drain_queue(queue, size=50, timeout=2.0):
        await api.bulk_submit(batch)

await asyncio.gather(producer(), consumer())
```

### Web crawler bulk insert

```python
for batch in batcher(crawler.records(), size=200, timeout=10.0):
    api.bulk_submit(batch)
```

---

## Tests

The test suite is organised by use case:

| File | What it covers |
|---|---|
| `tests/test_sync.py` | Core sync batcher behaviour |
| `tests/test_async.py` | Core async batcher behaviour |
| `tests/test_weighted.py` | Weighted batching (`max_weight`, `min_size`) — sync and async |
| `tests/test_drain_queue.py` | Queue draining (`drain_queue`, `STOP`) |
| `tests/test_kafka.py` | Kafka consumer patterns (sync + async) |
| `tests/test_db.py` | Database cursor and file iterator patterns |

---

## Roadmap

- **v0.1** — stable core: sync + async batching by size and timeout
- **v0.2** — PEP 561 typing, Python 3.13, async exception propagation, pattern test suites
- **v0.3** — async backpressure via bounded queue (`maxsize`)
- **v0.4** — weighted batching (`max_weight`, `weight`), flush metadata (`batcher_with_meta`), queue draining (`drain_queue`), `min_size` guard, convenience aliases
- **next** — docs site, additional convenience helpers

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
