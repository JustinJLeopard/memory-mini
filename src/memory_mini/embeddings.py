from __future__ import annotations

import math
import struct
from collections.abc import Callable, Iterable

Embedder = Callable[[str], Iterable[float]]


def pack_vector(values: Iterable[float]) -> tuple[bytes, int]:
    vector = [float(value) for value in values]
    return struct.pack(f"{len(vector)}f", *vector), len(vector)


def unpack_vector(blob: bytes, dims: int) -> list[float]:
    if dims < 1:
        return []
    return list(struct.unpack(f"{dims}f", blob))


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = [float(value) for value in left]
    right_values = [float(value) for value in right]
    if len(left_values) != len(right_values):
        raise ValueError("vector dimensions must match")
    dot = sum(a * b for a, b in zip(left_values, right_values, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left_values))
    right_norm = math.sqrt(sum(b * b for b in right_values))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def require_numpy() -> object:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - covered in no-numpy CI
        raise ImportError(
            "Vector search requires numpy. Install with: pip install memory-mini[embed]"
        ) from exc
    return np
