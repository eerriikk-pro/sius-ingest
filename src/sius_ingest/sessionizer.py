"""Deterministic lane-session and relay segmentation."""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from sius_ingest.models import (
    LaneState,
    SessionizerConfig,
    ShotAssignment,
    ShotKind,
    ShotMessage,
)


class RelaySessionizer:
    """Assign shots to athlete sessions, sighter blocks, and match relays.

    Observed range rules make the state machine deliberately simple:

    - a transition from match to sighter closes the match relay;
    - a transition from sighter to match starts a new match relay;
    - a non-increasing shot counter starts a new phase even without sighters;
    - relay length is never inferred from a nominal 60-shot course.
    """

    def __init__(self, config: SessionizerConfig | None = None) -> None:
        self._config = config or SessionizerConfig()

    def assign(
        self,
        *,
        range_id: str,
        shot: ShotMessage,
        shot_key: str,
        received_at: datetime,
        state: LaneState | None,
    ) -> ShotAssignment:
        shooter_number = shot.shooter_number
        new_session = self._starts_new_session(
            state=state,
            shooter_number=shooter_number,
            annual_ticks=shot.annual_ticks,
            received_at=received_at,
        )

        close_session_id = state.session_id if state and new_session else None
        close_phase_id = state.phase_id if state and new_session else None

        if new_session:
            session_id = _stable_id(
                "session",
                range_id,
                str(shot.lane_number),
                shot_key,
            )
            match_ordinal = 0
            sighter_ordinal = 0
            previous_phase = None
            previous_shot_number = None
        else:
            assert state is not None
            session_id = state.session_id
            match_ordinal = state.match_ordinal
            sighter_ordinal = state.sighter_ordinal
            previous_phase = state.phase_kind
            previous_shot_number = state.last_shot_number

        phase_kind = shot.shot_kind
        counter_restarted = (
            previous_shot_number is not None and shot.shot_number <= previous_shot_number
        )
        new_phase = new_session or previous_phase != phase_kind or counter_restarted

        if new_phase:
            if state and not new_session:
                close_phase_id = state.phase_id

            if phase_kind is ShotKind.MATCH:
                match_ordinal += 1
                phase_ordinal = match_ordinal
            else:
                sighter_ordinal += 1
                phase_ordinal = sighter_ordinal

            phase_id = _stable_id(
                "phase",
                range_id,
                str(shot.lane_number),
                phase_kind.value,
                shot_key,
            )
        else:
            assert state is not None
            phase_id = state.phase_id
            phase_ordinal = (
                state.match_ordinal if phase_kind is ShotKind.MATCH else state.sighter_ordinal
            )

        next_state = LaneState(
            range_id=range_id,
            lane_number=shot.lane_number,
            firing_point_index=shot.firing_point_index,
            shooter_number=shooter_number,
            session_id=session_id,
            phase_id=phase_id,
            phase_kind=phase_kind,
            last_shot_number=shot.shot_number,
            last_shot_key=shot_key,
            last_annual_ticks=shot.annual_ticks,
            last_activity_at=received_at,
            match_ordinal=match_ordinal,
            sighter_ordinal=sighter_ordinal,
        )
        return ShotAssignment(
            session_id=session_id,
            phase_id=phase_id,
            phase_kind=phase_kind,
            phase_ordinal=phase_ordinal,
            close_session_id=close_session_id,
            close_phase_id=close_phase_id,
            new_session=new_session,
            new_phase=new_phase,
            next_state=next_state,
        )

    def _starts_new_session(
        self,
        *,
        state: LaneState | None,
        shooter_number: str | None,
        annual_ticks: int,
        received_at: datetime,
    ) -> bool:
        if state is None:
            return True
        if state.shooter_number != shooter_number:
            return True

        # The observed annual counter advances by 100 ticks per second. This
        # preserves idle-gap detection when SIUSData replays a historical
        # backlog in a few seconds after a new connection.
        annual_tick_delta = annual_ticks - state.last_annual_ticks
        if annual_tick_delta >= 0:
            timeout_ticks = self._config.session_timeout.total_seconds() * 100
            if annual_tick_delta > timeout_ticks:
                return True

        idle_time = received_at - state.last_activity_at
        return idle_time > self._config.session_timeout


def _stable_id(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, "\0".join(("sius-ingest", *parts))))
