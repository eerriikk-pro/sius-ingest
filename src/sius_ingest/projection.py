"""Pure, deterministic projection of raw SIUS events into practice data."""

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from hashlib import sha256
from typing import Any

from sius_ingest.keys import shot_key
from sius_ingest.models import LaneState, SessionizerConfig, ShotMessage
from sius_ingest.parser import (
    PARSER_VERSION,
    ProtocolParseError,
    ProtocolParser,
    message_to_dict,
)
from sius_ingest.remote_source import RemoteRawEvent
from sius_ingest.sessionizer import RelaySessionizer
from sius_ingest.time_utils import isoformat_utc


@dataclass(frozen=True, slots=True)
class ProjectionPage:
    """Rows and state transitions produced by one ordered raw-event page."""

    processed_events: int
    parsed_shots: int
    duplicate_shots: int
    parse_errors: int
    quarantined_shots: int
    session_starts: tuple[dict[str, object], ...]
    phase_starts: tuple[dict[str, object], ...]
    session_activity: tuple[dict[str, object], ...]
    session_closures: tuple[dict[str, object], ...]
    phase_closures: tuple[dict[str, object], ...]
    shots: tuple[dict[str, object], ...]
    lane_states: tuple[dict[str, object], ...]
    errors: tuple[dict[str, object], ...]

    def payload(self) -> dict[str, object]:
        """Return the stable JSON object expected by the commit RPC."""

        return {
            "session_starts": list(self.session_starts),
            "phase_starts": list(self.phase_starts),
            "session_activity": list(self.session_activity),
            "session_closures": list(self.session_closures),
            "phase_closures": list(self.phase_closures),
            "shots": list(self.shots),
            "lane_states": list(self.lane_states),
            "errors": list(self.errors),
        }


@dataclass(slots=True)
class _MutableProjection:
    session_starts: dict[str, dict[str, object]] = field(default_factory=dict)
    phase_starts: dict[str, dict[str, object]] = field(default_factory=dict)
    session_activity: dict[str, dict[str, object]] = field(default_factory=dict)
    session_closures: dict[str, dict[str, object]] = field(default_factory=dict)
    phase_closures: dict[str, dict[str, object]] = field(default_factory=dict)
    shots: list[dict[str, object]] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)
    parsed_shots: int = 0
    duplicate_shots: int = 0
    parse_errors: int = 0
    quarantined_shots: int = 0


class ProjectionBuilder:
    """Project one event page from a supplied durable lane-state snapshot."""

    def __init__(
        self,
        *,
        lane_states: dict[tuple[str, int], LaneState],
        existing_shot_keys: set[str],
        session_timeout: timedelta = timedelta(hours=4),
        parser: ProtocolParser | None = None,
    ) -> None:
        self._lane_states = dict(lane_states)
        self._existing_shot_keys = set(existing_shot_keys)
        self._parser = parser or ProtocolParser()
        self._sessionizer = RelaySessionizer(SessionizerConfig(session_timeout=session_timeout))

    def build(self, events: list[RemoteRawEvent]) -> ProjectionPage:
        """Build deterministic row mutations without performing I/O."""

        changes = _MutableProjection()
        accepted_shot_keys: set[str] = set()

        for event in events:
            message = self._parse(event, changes)
            if not isinstance(message, ShotMessage):
                continue

            raw_hash = sha256(event.record.raw + event.record.delimiter).hexdigest()
            canonical_key = shot_key(event.range_id, message, raw_hash)
            if event.stable_event_key != canonical_key:
                changes.parse_errors += 1
                changes.errors.append(
                    _error_payload(
                        event,
                        kind="stable_key_mismatch",
                        message=(
                            "raw stable_event_key does not match the canonical "
                            f"shot key {canonical_key}"
                        ),
                    )
                )
                continue

            if canonical_key in self._existing_shot_keys or canonical_key in accepted_shot_keys:
                changes.duplicate_shots += 1
                continue

            state_key = (event.range_id, message.lane_number)
            previous_state = self._lane_states.get(state_key)
            if previous_state and _is_out_of_order(
                event=event,
                shot=message,
                state=previous_state,
            ):
                changes.quarantined_shots += 1
                changes.errors.append(
                    _error_payload(
                        event,
                        kind="out_of_order_shot",
                        message=(
                            "shot precedes the durable lane state; raw data was "
                            "retained but the projection was not changed"
                        ),
                    )
                )
                continue

            assignment = self._sessionizer.assign(
                range_id=event.range_id,
                shot=message,
                shot_key=canonical_key,
                received_at=event.record.completed_at,
                state=previous_state,
            )
            received_at = isoformat_utc(event.record.completed_at)
            previous_activity = (
                isoformat_utc(previous_state.last_activity_at) if previous_state else received_at
            )

            if assignment.new_session:
                changes.session_starts[assignment.session_id] = {
                    "id": assignment.session_id,
                    "range_id": event.range_id,
                    "lane_number": message.lane_number,
                    "firing_point_index": message.firing_point_index,
                    "shooter_number": message.shooter_number,
                    "started_at": received_at,
                    "last_activity_at": received_at,
                }
            if assignment.close_session_id:
                changes.session_closures[assignment.close_session_id] = {
                    "id": assignment.close_session_id,
                    "ended_at": previous_activity,
                }

            if assignment.new_phase:
                changes.phase_starts[assignment.phase_id] = {
                    "id": assignment.phase_id,
                    "session_id": assignment.session_id,
                    "range_id": event.range_id,
                    "lane_number": message.lane_number,
                    "phase_kind": assignment.phase_kind.value,
                    "ordinal": assignment.phase_ordinal,
                    "started_at": received_at,
                    "last_activity_at": received_at,
                }
            if assignment.close_phase_id:
                changes.phase_closures[assignment.close_phase_id] = {
                    "id": assignment.close_phase_id,
                    "ended_at": previous_activity,
                }

            changes.session_activity[assignment.session_id] = {
                "id": assignment.session_id,
                "firing_point_index": message.firing_point_index,
                "last_activity_at": received_at,
            }
            changes.shots.append(
                _shot_payload(
                    event=event,
                    shot=message,
                    canonical_key=canonical_key,
                    session_id=assignment.session_id,
                    phase_id=assignment.phase_id,
                )
            )
            changes.parsed_shots += 1
            accepted_shot_keys.add(canonical_key)
            self._lane_states[state_key] = assignment.next_state

        return ProjectionPage(
            processed_events=len(events),
            parsed_shots=changes.parsed_shots,
            duplicate_shots=changes.duplicate_shots,
            parse_errors=changes.parse_errors,
            quarantined_shots=changes.quarantined_shots,
            session_starts=tuple(changes.session_starts.values()),
            phase_starts=tuple(changes.phase_starts.values()),
            session_activity=tuple(changes.session_activity.values()),
            session_closures=tuple(changes.session_closures.values()),
            phase_closures=tuple(changes.phase_closures.values()),
            shots=tuple(changes.shots),
            lane_states=tuple(_lane_state_payload(state) for state in self._lane_states.values()),
            errors=tuple(changes.errors),
        )

    def _parse(
        self,
        event: RemoteRawEvent,
        changes: _MutableProjection,
    ) -> object | None:
        if not event.record.complete:
            changes.parse_errors += 1
            changes.errors.append(
                _error_payload(
                    event,
                    kind="incomplete_record",
                    message=event.record.partial_reason or "incomplete raw record",
                )
            )
            return None
        try:
            return self._parser.parse(event.record.raw)
        except ProtocolParseError as exc:
            changes.parse_errors += 1
            changes.errors.append(
                _error_payload(
                    event,
                    kind="parse_error",
                    message=str(exc),
                )
            )
            return None


def _is_out_of_order(
    *,
    event: RemoteRawEvent,
    shot: ShotMessage,
    state: LaneState,
) -> bool:
    received_at = event.record.completed_at
    if received_at < state.last_activity_at:
        return True
    return (
        received_at.year == state.last_activity_at.year
        and shot.annual_ticks < state.last_annual_ticks
    )


def _shot_payload(
    *,
    event: RemoteRawEvent,
    shot: ShotMessage,
    canonical_key: str,
    session_id: str,
    phase_id: str,
) -> dict[str, object]:
    return {
        "shot_key": canonical_key,
        "raw_event_key": event.event_key,
        "session_id": session_id,
        "phase_id": phase_id,
        "range_id": event.range_id,
        "lane_number": shot.lane_number,
        "firing_point_index": shot.firing_point_index,
        "shooter_number": shot.shooter_number,
        "received_at": isoformat_utc(event.record.completed_at),
        "device_time_text": shot.device_time_text,
        "annual_ticks": shot.annual_ticks,
        "event_sequence": shot.event_sequence,
        "phase_kind": shot.shot_kind.value,
        "shot_number": shot.shot_number,
        "score_integer": shot.integer_score,
        "score_tenths": shot.score_tenths,
        "primary_score_raw": shot.primary_score_raw,
        "secondary_score_raw": shot.secondary_score_raw,
        "shot_flags_raw": shot.shot_flags_raw,
        "exercise_code_raw": shot.exercise_code_raw,
        "x_native": str(shot.x_native),
        "y_native": str(shot.y_native),
        "parser_version": PARSER_VERSION,
        "payload": message_to_dict(shot),
    }


def _lane_state_payload(state: LaneState) -> dict[str, object]:
    payload = asdict(state)
    payload["phase_kind"] = state.phase_kind.value
    payload["last_activity_at"] = isoformat_utc(state.last_activity_at)
    return payload


def _error_payload(
    event: RemoteRawEvent,
    *,
    kind: str,
    message: str,
) -> dict[str, Any]:
    return {
        "ingest_id": event.ingest_id,
        "event_key": event.event_key,
        "range_id": event.range_id,
        "error_kind": kind,
        "error_message": message[:2000],
    }
