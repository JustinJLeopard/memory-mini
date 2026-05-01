# Embeddings

Embeddings are optional. `memory-mini` does not call any external API or ship a built-in model. Provide a callable that converts text into floats.

```python
from memory_mini import Store

def embed(text: str) -> list[float]:
    return [float(len(text)), float(text.count("release"))]

with Store("memory.db") as memory:
    memory.embed_and_store("release-note", "release shipped", embed, "sessions")
    results = memory.embed_and_search("release", embed, ns="sessions", k=1)
```

Vectors are stored as `float32` blobs with model name and dimension metadata. Vector search imports `numpy` only when search is requested; install it with:

```bash
pip install memory-mini[embed]
```
