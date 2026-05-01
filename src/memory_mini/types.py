from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EntryStatus(StrEnum):
    ACTIVE = "active"
    SOFT_DELETED = "soft-deleted"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Namespace:
    name: str = "default"


@dataclass(frozen=True)
class Query:
    text: str
    namespace: str | None = None
    include_deleted: bool = False
    limit: int = 20


@dataclass(frozen=True)
class Entry:
    key: str
    value: str
    namespace: str = "default"
    status: EntryStatus = EntryStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_accessed_at: datetime | None = None
    expires_at: datetime | None = None
    embedding_model: str | None = None
    embedding_dims: int | None = None
