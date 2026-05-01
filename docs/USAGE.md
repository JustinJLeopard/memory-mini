# Usage

`memory-mini` stores text values by `(namespace, key)` in SQLite.

```python
from memory_mini import Store

with Store("memory.db") as memory:
    memory.store("preference/theme", "dark", "user/settings")
    entry = memory.get("preference/theme", "user/settings")
    assert entry.value == "dark"
```

Namespaces are normalized path-like strings. `project/topic` and `/project/topic/` refer to the same namespace.

## CLI

```bash
memory-mini --db memory.db store session-end-1 "Finished release" --namespace sessions/app
memory-mini --db memory.db get session-end-1 --namespace sessions/app
memory-mini --db memory.db search session --mode prefix
memory-mini --db memory.db stats
```

The `store` command uses upsert by default. Pass `--no-upsert` only when duplicate writes should fail.
