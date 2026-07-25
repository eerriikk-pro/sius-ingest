"""Typed transport, protocol, and relay-domain models."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

SocketAddress: TypeAlias = tuple[str, int]


@dataclass(frozen=True, slots=True)
class ConnectionOpened:
    """A TCP connection was established."""

    connection_id: UUID
    occurred_at: datetime
    local_address: SocketAddress
    peer_address: SocketAddress


@dataclass(frozen=True, slots=True)
class TcpChunk:
    """One byte chunk returned by ``socket.recv``."""

    connection_id: UUID
    sequence: int
    received_at: datetime
    data: bytes


@dataclass(frozen=True, slots=True)
class ConnectionClosed:
    """A connection ended or a connection attempt failed."""

    connection_id: UUID
    occurred_at: datetime
    error: str | None
    will_reconnect: bool


SourceEvent: TypeAlias = ConnectionOpened | TcpChunk | ConnectionClosed


@dataclass(frozen=True, slots=True)
class FramedRecord:
    """A tentative newline-delimited record derived from TCP chunks."""

    connection_id: UUID
    sequence: int
    completed_at: datetime
    raw: bytes
    delimiter: bytes
    complete: bool
    partial_reason: str | None = None


class ShotKind(StrEnum):
    """Observed practice phase represented by a shot."""

    SIGHTER = "sighter"
    MATCH = "match"


@dataclass(frozen=True, slots=True)
class GenericMessage:
    """A recognized SIUS record without a type-specific field mapping."""

    record_type: str
    fields: tuple[str, ...]
    firing_point_index: int | None
    lane_number: int | None
    shooter_number: str | None
    event_sequence: int | None
    device_time_text: str | None
    annual_ticks: int | None


@dataclass(frozen=True, slots=True)
class ShooterIdentityMessage:
    """An observed ``_SHID`` firing-number announcement."""

    record_type: str
    fields: tuple[str, ...]
    firing_point_index: int
    lane_number: int
    shooter_number: str | None
    identity_kind_raw: int
    external_number: str | None


@dataclass(frozen=True, slots=True)
class ShotMessage:
    """Observed-v1 mapping for a ``_SHOT`` record.

    Fields whose SIUS meaning is not yet established retain a ``*_raw`` name.
    """

    record_type: str
    fields: tuple[str, ...]
    firing_point_index: int
    lane_number: int
    shooter_number: str | None
    stream_code_raw: int
    event_sequence: int
    device_time_text: str
    message_code_raw: int
    exercise_code_raw: int
    shot_flags_raw: int
    primary_score_raw: int
    secondary_score_raw: int
    indicator_raw: int
    shot_number: int
    x_native: Decimal
    y_native: Decimal
    distance_raw: int
    unknown_17_raw: int
    unknown_18_raw: int
    sentinel_raw: Decimal
    annual_ticks: int
    target_type_raw: int
    target_width_raw: int
    target_id_raw: int

    @property
    def shot_kind(self) -> ShotKind:
        """Classify the observed sighter flag.

        Controlled range tests found ``39`` for sighters and ``7`` for match
        shots. Their only difference is bit ``0x20``.
        """

        if self.shot_flags_raw & 0x20:
            return ShotKind.SIGHTER
        return ShotKind.MATCH

    @property
    def score_tenths(self) -> int:
        """Normalize observed score encodings to integer tenths.

        Some exercises emit integer and decimal scores separately (``9;94``);
        another observed exercise emits the decimal score as primary
        (``94;0``).
        """

        if self.secondary_score_raw > 0:
            return self.secondary_score_raw
        if self.primary_score_raw > 10:
            return self.primary_score_raw
        return self.primary_score_raw * 10

    @property
    def integer_score(self) -> int:
        if self.secondary_score_raw > 0:
            return self.primary_score_raw
        if self.primary_score_raw > 10:
            return self.primary_score_raw // 10
        return self.primary_score_raw


ParsedMessage: TypeAlias = GenericMessage | ShooterIdentityMessage | ShotMessage


@dataclass(frozen=True, slots=True)
class LaneState:
    """Persisted state needed to segment one lane deterministically."""

    range_id: str
    lane_number: int
    firing_point_index: int
    shooter_number: str | None
    session_id: str
    phase_id: str
    phase_kind: ShotKind
    last_shot_number: int
    last_shot_key: str
    last_annual_ticks: int
    last_activity_at: datetime
    match_ordinal: int
    sighter_ordinal: int


@dataclass(frozen=True, slots=True)
class ShotAssignment:
    """Session and phase decision for a newly accepted shot."""

    session_id: str
    phase_id: str
    phase_kind: ShotKind
    phase_ordinal: int
    close_session_id: str | None
    close_phase_id: str | None
    new_session: bool
    new_phase: bool
    next_state: LaneState


@dataclass(frozen=True, slots=True)
class SessionizerConfig:
    """Relay segmentation policy."""

    session_timeout: timedelta = timedelta(hours=4)

    def __post_init__(self) -> None:
        if self.session_timeout <= timedelta(0):
            raise ValueError("session_timeout must be positive")


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome returned after one framed record is persisted."""

    observation_inserted: bool
    message_type: str | None
    parse_error: str | None
    shot_inserted: bool
    shot_duplicate: bool
    shot_key: str | None
    lane_number: int | None
    shooter_number: str | None
    shot_kind: ShotKind | None
    shot_number: int | None
    score_tenths: int | None
    session_id: str | None
    phase_id: str | None


@dataclass(frozen=True, slots=True)
class OutboxItem:
    """One versioned remote-upsert job."""

    id: int
    topic: str
    dedupe_key: str
    payload: dict[str, object]
    revision: int
    attempt_count: int


@dataclass(frozen=True, slots=True)
class StoreStatus:
    """Small operational summary for the CLI."""

    raw_events: int
    shots: int
    sessions: int
    phases: int
    pending_uploads: int
    failed_uploads: int
