# Lifecycle

`memory-mini` separates logical deletion from physical cleanup.

## Soft-delete

`soft_delete(key, namespace)` changes an entry status to `soft-deleted`. Normal `get`, `list`, and `search` calls ignore soft-deleted entries. Pass `include_deleted=True` when you need to inspect retained records.

## Cleanup

`cleanup()` hard-removes soft-deleted rows after the retention window.

```python
from datetime import timedelta

memory.cleanup(retention=timedelta(days=30))
```

Use `cleanup(all_deleted=True)` for a deliberate purge of every soft-deleted row. Active entries are never removed by cleanup.

## Expiration

Entries can be written with `expires_at`. Expired entries are hidden from normal reads and marked `expired` when encountered.
