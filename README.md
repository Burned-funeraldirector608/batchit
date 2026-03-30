# batchit

> Tiny batching for Python pipelines, streams, and agent workflows.

[![PyPI version](https://img.shields.io/pypi/v/batchit.svg?cacheSeconds=60)](https://pypi.org/project/batchit/)
[![Python versions](https://img.shields.io/pypi/pyversions/batchit.svg?cacheSeconds=60)](https://pypi.org/project/batchit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/Ahmedie-m/batchit/actions/workflows/ci.yml/badge.svg)](https://github.com/Ahmedie-m/batchit/actions/workflows/ci.yml)

Batch any Python iterator by **count**, **elapsed time**, or both — in one `pip install`, with no dependencies.

```python
from batchit import batcher, async_batcher

# Sync — flush every 100 items or when the next item reveals 5 s have passed
for batch in batcher(source, size=100, timeout=5.0):
    db.bulk_insert(batch)

# Async — flush every 100 items or after 5 s of silence from the source
async for batch in async_batcher(source, size=100, timeout=5.0):
    await db.bulk_insert(batch)
```

---

## AI / agent pipelines

```python
# Batch embedding requests before upserting to a vector store
async for batch in async_batcher(document_stream(), size=96, timeout=2.0):
    vectors = await embed(batch)
    await vector_store.upsert(vectors)

# Batch agent tool outputs before writing to Postgres
async for batch in async_batcher(tool_result_stream(), size=50, timeout=1.0):
    await db.execute("INSERT INTO results ...", batch)

# Batch scraped records before bulk API submission
for batch in batcher(scraper.records(), size=200, timeout=10.0):
    api.bulk_submit(batch)

# Batch trace/log events before shipping to observability backend
async for batch in async_batcher(event_stream(), size=500, timeout=5.0, maxsize=1000):
    await telemetry.ingest(batch)
```

---

## Why not just write this yourself?

You could — it's not a lot of code. But here's what you'd need to get right:

- **Sync and async** variants with consistent semantics
- **Partial final batch** always flushed, never silently dropped
- **Timeout measured correctly** from the first item in the batch, not wall clock
- **Async timeout fires independently** of item delivery (via `asyncio.wait_for`) — not just on arrival
- **Backpressure** support via bounded internal queue
- **Exception propagation** from the source through to the consumer
- **PEP 561 typing** so your IDE and type checker understand the API
- **Tested** across Python 3.10–3.13

`pip install batchit` and move on.

---

## Why batchit?

`more-itertools.batched()` batches by count only. In real streaming workloads
(Kafka consumers, database cursors, API result streams) you also need a **time
window**. Every team writes this boilerplate. `batchit` is the one-liner that replaces it.

| | Count limit | Time limit | Async | Backpressure | Dependencies |
|---|:---:|:---:|:---:|:---:|:---:|
| `batchit` | ✓ | ✓ | ✓ | ✓ | none |
| `more-itertools` | ✓ | ✗ | ✗ | ✗ | 1 |
| `toolz` | ✓ | ✗ | ✗ | ✗ | 1 |
| hand-rolled | maybe | maybe | maybe | maybe | — |

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
```

### Async — `async_batcher`

```python
from batchit import async_batcher

async for batch in async_batcher(async_source, size=100, timeout=5.0):
    await db.bulk_insert(batch)

# With backpressure — producer blocks if more than 200 items are queued
async for batch in async_batcher(fast_source, size=50, timeout=2.0, maxsize=200):
    await slow_downstream(batch)
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

### `batcher(iterable, *, size=None, timeout=None)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `iterable` | `Iterable[T]` | Any iterable to batch |
| `size` | `int \| None` | Max items per batch |
| `timeout` | `float \| None` | Max seconds per batch, measured from the first item |

Yields `list[T]`. At least one of `size` / `timeout` must be provided.

### `async_batcher(aiterable, *, size=None, timeout=None, maxsize=0)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `aiterable` | `AsyncIterable[T]` | Any async iterable to batch |
| `size` | `int \| None` | Max items per batch |
| `timeout` | `float \| None` | Max seconds per batch, measured from the first item |
| `maxsize` | `int` | Internal queue cap for backpressure. `0` = unbounded |

Yields `list[T]` asynchronously.

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
| `tests/test_kafka.py` | Kafka consumer patterns (sync + async) |
| `tests/test_db.py` | Database cursor and file iterator patterns |

---

## Roadmap

- **v0.1** — stable core: sync + async batching by size and timeout
- **v0.2** — PEP 561 typing, Python 3.13, async exception propagation, pattern test suites
- **v0.3** — async backpressure via bounded queue (`maxsize`)
- **next** — docs site, additional convenience helpers

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
