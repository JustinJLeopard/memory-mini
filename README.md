# memory-mini

Minimal reference for durable agent memory: namespaced key-value storage with upsert, soft-delete, cleanup, optional embeddings, and SQLite durability.

`memory-mini` is intentionally small. It is a local reference implementation
for inspecting namespaced SQLite storage, lifecycle operations, upserts,
retention, and optional embedding helpers. Its scope is the code and tests in
this repository, not a hosted memory service or a production-readiness claim.

## What to inspect

- [`store.py`](src/memory_mini/store.py) defines the SQLite schema, the
  `(namespace, key)` uniqueness rule, and the `ON CONFLICT` upsert path.
- [`store.py`](src/memory_mini/store.py) keeps soft-delete and retention-based
  cleanup as separate operations.
- [`namespace.py`](src/memory_mini/namespace.py) contains the path-like
  namespace normalization and traversal helpers.
- [`embeddings.py`](src/memory_mini/embeddings.py) contains the optional vector
  helpers; the package has no required runtime dependencies.

## Install

Install directly from the Git repository. Use the base command or the command
with the optional embedding dependency:

```bash
# Base package
python -m pip install "memory-mini @ git+https://github.com/JustinJLeopard/memory-mini.git@main"

# Base package plus NumPy-backed embedding helpers
python -m pip install "memory-mini[embed] @ git+https://github.com/JustinJLeopard/memory-mini.git@main"
```

There is currently no PyPI release for this package.

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

## Related

- [JustAi](https://github.com/JustinJLeopard/JustAi) — orchestration control plane.
- [safe-mini](https://github.com/JustinJLeopard/safe-mini) — safe local execution substrate.
- [route-mini](https://github.com/JustinJLeopard/route-mini) — routing policy reference.
