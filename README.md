# memory-mini

Minimal reference for durable agent memory: namespaced key-value storage with upsert, soft-delete, cleanup, optional embeddings, and SQLite durability.

## Install

```bash
pip install memory-mini
pip install memory-mini[embed]
```

## 30-second example

```python
from datetime import timedelta
from memory_mini import Store

with Store("memory.db") as memory:
    memory.store("session-end-2026-05-01-1", "Shipped docs and tests.", "sessions/project")
    memory.store("session-end-2026-05-01-1", "Shipped docs, tests, and CI.", "sessions/project")

    print(memory.get("session-end-2026-05-01-1", "sessions/project").value)

    memory.soft_delete("session-end-2026-04-01-1", "sessions/project")
    memory.cleanup(retention=timedelta(days=30))
```

## Why upsert-first?

Durable memory should treat repeated writes as a normal update path. A delete-then-store workflow creates avoidable failure modes: unique keys can remain reserved by soft-deleted rows, audit history becomes ambiguous, and callers have to coordinate two operations instead of one. `memory-mini` defaults to upsert so storing the same namespaced key again refreshes the active entry in a single transaction.

Soft-delete and cleanup are deliberately separate. Soft-delete hides an entry from normal reads while preserving recoverability. Cleanup is the explicit hard-removal step, usually run after a retention window.

## Docs

- [Usage](docs/USAGE.md)
- [Lifecycle](docs/LIFECYCLE.md)
- [Embeddings](docs/EMBEDDINGS.md)
