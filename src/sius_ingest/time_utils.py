"""Time helpers kept in one place for consistent UTC timestamps."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
