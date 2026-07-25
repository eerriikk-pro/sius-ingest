"""Conservative parser for the SIUSData records observed at the range."""

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from sius_ingest.models import (
    GenericMessage,
    ParsedMessage,
    ShooterIdentityMessage,
    ShotMessage,
)

PARSER_VERSION = "observed-v1"


class ProtocolParseError(ValueError):
    """A record had a recognized shape but invalid fields."""


class ProtocolParser:
    """Parse known messages while retaining unknown messages generically."""

    def parse(self, raw: bytes) -> ParsedMessage:
        text = raw.decode("latin-1")
        fields = tuple(text.split(";"))
        if not fields or not fields[0]:
            raise ProtocolParseError("empty SIUS record")
        if not fields[0].startswith("_"):
            raise ProtocolParseError(f"invalid record type: {fields[0]!r}")

        if fields[0] == "_SHOT":
            return self._parse_shot(fields)
        if fields[0] == "_SHID":
            return self._parse_identity(fields)
        return self._parse_generic(fields)

    def _parse_shot(self, fields: tuple[str, ...]) -> ShotMessage:
        if len(fields) < 24:
            raise ProtocolParseError(f"_SHOT requires at least 24 fields; received {len(fields)}")

        return ShotMessage(
            record_type=fields[0],
            fields=fields,
            firing_point_index=_required_int(fields, 1, "firing_point_index"),
            lane_number=_required_int(fields, 2, "lane_number"),
            shooter_number=_optional_identifier(fields[3]),
            stream_code_raw=_required_int(fields, 4, "stream_code_raw"),
            event_sequence=_required_int(fields, 5, "event_sequence"),
            device_time_text=fields[6],
            message_code_raw=_required_int(fields, 7, "message_code_raw"),
            exercise_code_raw=_required_int(fields, 8, "exercise_code_raw"),
            shot_flags_raw=_required_int(fields, 9, "shot_flags_raw"),
            primary_score_raw=_required_int(fields, 10, "primary_score_raw"),
            secondary_score_raw=_required_int(fields, 11, "secondary_score_raw"),
            indicator_raw=_required_int(fields, 12, "indicator_raw"),
            shot_number=_required_int(fields, 13, "shot_number"),
            x_native=_required_decimal(fields, 14, "x_native"),
            y_native=_required_decimal(fields, 15, "y_native"),
            distance_raw=_required_int(fields, 16, "distance_raw"),
            unknown_17_raw=_required_int(fields, 17, "unknown_17_raw"),
            unknown_18_raw=_required_int(fields, 18, "unknown_18_raw"),
            sentinel_raw=_required_decimal(fields, 19, "sentinel_raw"),
            annual_ticks=_required_int(fields, 20, "annual_ticks"),
            target_type_raw=_required_int(fields, 21, "target_type_raw"),
            target_width_raw=_required_int(fields, 22, "target_width_raw"),
            target_id_raw=_required_int(fields, 23, "target_id_raw"),
        )

    def _parse_identity(self, fields: tuple[str, ...]) -> ShooterIdentityMessage:
        if len(fields) < 6:
            raise ProtocolParseError(f"_SHID requires at least 6 fields; received {len(fields)}")
        return ShooterIdentityMessage(
            record_type=fields[0],
            fields=fields,
            firing_point_index=_required_int(fields, 1, "firing_point_index"),
            lane_number=_required_int(fields, 2, "lane_number"),
            shooter_number=_optional_identifier(fields[3]),
            identity_kind_raw=_required_int(fields, 4, "identity_kind_raw"),
            external_number=_optional_identifier(fields[5]),
        )

    def _parse_generic(self, fields: tuple[str, ...]) -> GenericMessage:
        firing_point = _optional_int_at(fields, 1)
        lane = _optional_int_at(fields, 2)
        shooter = _optional_identifier(fields[3]) if len(fields) > 3 else None

        event_sequence = None
        device_time = None
        annual_ticks = None
        if len(fields) > 6 and _looks_like_device_time(fields[6]):
            event_sequence = _optional_int_at(fields, 5)
            device_time = fields[6]
            annual_ticks = _last_integer(fields)

        return GenericMessage(
            record_type=fields[0],
            fields=fields,
            firing_point_index=firing_point,
            lane_number=lane,
            shooter_number=shooter,
            event_sequence=event_sequence,
            device_time_text=device_time,
            annual_ticks=annual_ticks,
        )


def message_to_dict(message: ParsedMessage) -> dict[str, Any]:
    """Convert a parsed dataclass to JSON-safe primitives."""

    return _json_safe(asdict(message))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _required_int(fields: tuple[str, ...], index: int, name: str) -> int:
    try:
        return int(fields[index])
    except (IndexError, ValueError) as exc:
        value = fields[index] if index < len(fields) else None
        raise ProtocolParseError(f"{name} must be an integer; received {value!r}") from exc


def _required_decimal(fields: tuple[str, ...], index: int, name: str) -> Decimal:
    try:
        return Decimal(fields[index])
    except (IndexError, InvalidOperation) as exc:
        value = fields[index] if index < len(fields) else None
        raise ProtocolParseError(f"{name} must be decimal; received {value!r}") from exc


def _optional_int_at(fields: tuple[str, ...], index: int) -> int | None:
    if index >= len(fields) or not fields[index]:
        return None
    try:
        return int(fields[index])
    except ValueError:
        return None


def _optional_identifier(value: str) -> str | None:
    stripped = value.strip()
    if not stripped or stripped == "0":
        return None
    return stripped


def _looks_like_device_time(value: str) -> bool:
    parts = value.split(":")
    return len(parts) == 3 and all(parts[:2]) and "." in parts[2]


def _last_integer(fields: tuple[str, ...]) -> int | None:
    for value in reversed(fields):
        if not value:
            continue
        try:
            return int(value)
        except ValueError:
            return None
    return None
