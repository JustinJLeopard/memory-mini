from __future__ import annotations

import re

from memory_mini.types import Entry, EntryStatus


def filter_prefix(entries: list[Entry], prefix: str) -> list[Entry]:
    return [entry for entry in entries if entry.key.startswith(prefix)]


def filter_regex(entries: list[Entry], pattern: str) -> list[Entry]:
    compiled = re.compile(pattern)
    return [
        entry
        for entry in entries
        if compiled.search(entry.key)
        or compiled.search(entry.value)
        or compiled.search(entry.namespace)
    ]


def visible_statuses(include_deleted: bool) -> tuple[EntryStatus, ...]:
    if include_deleted:
        return (EntryStatus.ACTIVE, EntryStatus.SOFT_DELETED, EntryStatus.EXPIRED)
    return (EntryStatus.ACTIVE,)
