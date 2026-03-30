# batchit

[![PyPI version](https://img.shields.io/pypi/v/batchit.svg)](https://pypi.org/project/batchit/)
[![Python versions](https://img.shields.io/pypi/pyversions/batchit.svg)](https://pypi.org/project/batchit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/Ahmedie-m/batchit/actions/workflows/ci.yml/badge.svg)](https://github.com/Ahmedie-m/batchit/actions/workflows/ci.yml)

Batch any Python iterator by **count**, **elapsed time**, or both.

```python
from batchit import batcher

for batch in batcher(source, size=100, timeout=5.0):
    db.bulk_insert(batch)   # never waits more than 5 s; never more than 100 items
```

## Why batchit?

`more-itertools.batched()` batches by count only.  In real streaming workloads
(Kafka consumers, database cursors, API result streams) you also need a **time
window**: flush whatever you have after *N* seconds, even if the count hasn't
been reached yet.  Every team writes this boilerplate from scratch.  `batchit`
is that one `pip install` away.

| | Count limit | Time limit | Async | Dependencies |
|---|:---:|:---:|:---:|:---:|
| `batchit` | ✓ | ✓ | ✓ | none |
| `more-itertools` | ✓ | ✗ | ✗ | 1 |
| `toolz` | ✓ | ✗ | ✗ | 1 |
| hand-rolled | maybe | maybe | maybe | — |

## Installation

```bash
pip install batchit
```

No runtime dependencies.  Python 3.10–3.13.  Fully typed (PEP 561).

## Usage

### Sync — `batcher`

```python
from batchit import batcher

# By size only
for batch in batcher(range(1000), size=50):
    process(batch)

# By timeout only (flush every 5 seconds)
for batch in batcher(kafka_consumer, timeout=5.0):
    send_to_api(batch)

# By both — whichever fires first
for batch in batcher(db_cursor, size=200, timeout=10.0):
    write_to_s3(batch)
```

The timeout is measured from the **first item** in the current batch, so no
threads or background tasks are needed.  Works with any iterable: generators,
Kafka consumers, database cursors, file readers.

### Async — `async_batcher`

```python
from batchit import async_batcher

async for batch in async_batcher(async_source, size=100, timeout=5.0):
    await db.bulk_insert(batch)
```

The async variant uses `asyncio.wait_for` internally, so it flushes a batch
even when the upstream source **stalls** — no items need to arrive to trigger
the timeout.

## API

### `batcher(iterable, *, size=None, timeout=None)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `iterable` | `Iterable[T]` | Any iterable to batch |
| `size` | `int \| None` | Max items per batch |
| `timeout` | `float \| None` | Max seconds per batch |

Yields `list[T]`.  At least one of `size` / `timeout` must be provided.
Remaining items at end of the iterable are always yielded (no silent drops).

### `async_batcher(aiterable, *, size=None, timeout=None)`

Same parameters, accepts `AsyncIterable[T]`, yields `list[T]` asynchronously.

## Real-world patterns

**Kafka consumer with time-based flush:**
```python
from kafka import KafkaConsumer
from batchit import batcher

consumer = KafkaConsumer("my-topic")
for batch in batcher(consumer, size=500, timeout=10.0):
    db.bulk_insert([msg.value for msg in batch])
    consumer.commit()
```

**Database cursor in chunks:**
```python
cursor.execute("SELECT * FROM events")
for batch in batcher(cursor, size=1000):
    warehouse.insert_many(batch)
```

**Async HTTP stream:**
```python
async for batch in async_batcher(response.content, size=64, timeout=2.0):
    await storage.write(batch)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
