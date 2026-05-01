from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso_now() -> str:
    return utc_now().isoformat()


def to_iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


def from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def cleanup_cutoff(retention: timedelta | None) -> str | None:
    if retention is None:
        return None
    return (utc_now() - retention).isoformat()
