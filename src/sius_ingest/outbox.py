"""Durable SQLite event store and versioned upload outbox."""

import json
import sqlite3
from base64 import b64encode
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import Any

from sius_ingest.models import (
    FramedRecord,
    GenericMessage,
    IngestResult,
    LaneState,
    OutboxItem,
    ParsedMessage,
    ProjectionCursor,
    ShotAssignment,
    ShotKind,
    ShotMessage,
    StoreStatus,
)
from sius_ingest.parser import message_to_dict
from sius_ingest.sessionizer import RelaySessionizer
from sius_ingest.time_utils import isoformat_utc, parse_utc, utc_now

SCHEMA_VERSION = 2

REMOTE_RAW_EVENTS = "sius_raw_events"
REMOTE_SESSIONS = "sius_sessions"
REMOTE_PHASES = "sius_phases"
REMOTE_SHOTS = "sius_shots"


class SQLiteEventStore(AbstractContextManager["SQLiteEventStore"]):
    """Persist observations, canonical shots, relay state, and upload jobs."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self._connection = sqlite3.connect(database_path, timeout=10)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 10000")
        self._migrate()

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def persist_record(
        self,
        *,
        record: FramedRecord,
        message: ParsedMessage | None,
        parse_error: str | None,
        parser_version: str,
        range_id: str,
        sessionizer: RelaySessionizer,
        project_locally: bool = True,
        enqueue_raw_upload: bool = True,
        source_event_key: str | None = None,
    ) -> IngestResult:
        raw_with_delimiter = record.raw + record.delimiter
        raw_hash = sha256(raw_with_delimiter).hexdigest()
        observation_key = _observation_key(record, raw_hash)
        message_type = _message_type(message, record.raw)
        stable_event_key = _stable_event_key(
            range_id=range_id,
            message=message,
            message_type=message_type,
            raw_hash=raw_hash,
        )
        remote_event_key = source_event_key or observation_key
        parsed_payload = message_to_dict(message) if message else None
        lane_number = _lane_number(message)
        shooter_number = _shooter_number(message)
        raw_text = record.raw.decode("latin-1")
        fields = list(message.fields) if message else raw_text.split(";")

        with self._connection:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO raw_events (
                    observation_key,
                    stable_event_key,
                    connection_id,
                    record_sequence,
                    received_at,
                    event_type,
                    lane_number,
                    raw_bytes,
                    delimiter_bytes,
                    raw_sha256,
                    complete,
                    parser_version,
                    parsed_json,
                    parse_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_key,
                    stable_event_key,
                    str(record.connection_id),
                    record.sequence,
                    isoformat_utc(record.completed_at),
                    message_type,
                    lane_number,
                    record.raw,
                    record.delimiter,
                    raw_hash,
                    int(record.complete),
                    parser_version,
                    _json_dumps(parsed_payload) if parsed_payload is not None else None,
                    parse_error,
                ),
            )
            observation_inserted = cursor.rowcount != 0
            if not observation_inserted and not project_locally:
                return _result(
                    observation_inserted=False,
                    message_type=message_type,
                    parse_error=parse_error,
                    lane_number=lane_number,
                    shooter_number=shooter_number,
                )

            if observation_inserted:
                raw_event_id = int(cursor.lastrowid)
                if enqueue_raw_upload:
                    self._enqueue(
                        cursor,
                        topic=REMOTE_RAW_EVENTS,
                        dedupe_key=remote_event_key,
                        payload={
                            "event_key": remote_event_key,
                            "stable_event_key": stable_event_key,
                            "range_id": range_id,
                            "connection_id": str(record.connection_id),
                            "record_sequence": record.sequence,
                            "firing_point_index": _message_attribute(
                                message,
                                "firing_point_index",
                            ),
                            "lane_number": lane_number,
                            "shooter_number": shooter_number,
                            "event_type": message_type,
                            "event_sequence": _message_attribute(message, "event_sequence"),
                            "device_time_text": _message_attribute(
                                message,
                                "device_time_text",
                            ),
                            "annual_ticks": _message_attribute(message, "annual_ticks"),
                            "received_at": isoformat_utc(record.completed_at),
                            "raw_text": raw_text,
                            "fields": fields,
                            "raw_base64": b64encode(record.raw).decode("ascii"),
                            "delimiter_base64": b64encode(record.delimiter).decode("ascii"),
                            "raw_size_bytes": len(record.raw),
                            "raw_sha256": raw_hash,
                            "complete": record.complete,
                            "partial_reason": record.partial_reason,
                            "parser_version": parser_version,
                            "parsed": parsed_payload,
                            "parse_error": parse_error,
                        },
                        coalesce=False,
                    )
            else:
                row = cursor.execute(
                    "SELECT id FROM raw_events WHERE observation_key = ?",
                    (observation_key,),
                ).fetchone()
                assert row is not None
                raw_event_id = int(row["id"])

            if not isinstance(message, ShotMessage):
                return _result(
                    observation_inserted=observation_inserted,
                    message_type=message_type,
                    parse_error=parse_error,
                    lane_number=lane_number,
                    shooter_number=shooter_number,
                )

            shot_key = _shot_key(range_id, message, raw_hash)
            if not project_locally:
                return _result(
                    observation_inserted=observation_inserted,
                    message_type=message_type,
                    parse_error=parse_error,
                    shot_key=shot_key,
                    lane_number=message.lane_number,
                    shooter_number=message.shooter_number,
                    shot_kind=message.shot_kind,
                    shot_number=message.shot_number,
                    score_tenths=message.score_tenths,
                )

            existing_shot = cursor.execute(
                "SELECT 1 FROM shots WHERE shot_key = ?",
                (shot_key,),
            ).fetchone()
            if existing_shot:
                return _result(
                    observation_inserted=observation_inserted,
                    message_type=message_type,
                    parse_error=parse_error,
                    shot_duplicate=True,
                    shot_key=shot_key,
                    lane_number=message.lane_number,
                    shooter_number=message.shooter_number,
                    shot_kind=message.shot_kind,
                    shot_number=message.shot_number,
                    score_tenths=message.score_tenths,
                )

            state = self._load_lane_state(
                cursor,
                range_id=range_id,
                lane_number=message.lane_number,
            )
            assignment = sessionizer.assign(
                range_id=range_id,
                shot=message,
                shot_key=shot_key,
                received_at=record.completed_at,
                state=state,
            )
            self._apply_assignment(
                cursor=cursor,
                range_id=range_id,
                record=record,
                raw_event_id=raw_event_id,
                raw_event_key=remote_event_key,
                shot=message,
                shot_key=shot_key,
                parsed_payload=parsed_payload,
                parser_version=parser_version,
                assignment=assignment,
                previous_state=state,
            )

            return _result(
                observation_inserted=observation_inserted,
                message_type=message_type,
                parse_error=parse_error,
                shot_inserted=True,
                shot_key=shot_key,
                lane_number=message.lane_number,
                shooter_number=message.shooter_number,
                shot_kind=message.shot_kind,
                shot_number=message.shot_number,
                score_tenths=message.score_tenths,
                session_id=assignment.session_id,
                phase_id=assignment.phase_id,
            )

    def pending_outbox(
        self,
        *,
        limit: int,
        topics: Sequence[str] | None = None,
    ) -> list[OutboxItem]:
        now = isoformat_utc(utc_now())
        topic_filter = ""
        parameters: list[object] = [now]
        if topics:
            placeholders = ",".join("?" for _ in topics)
            topic_filter = f" AND topic IN ({placeholders})"
            parameters.extend(topics)
        parameters.append(limit)
        rows = self._connection.execute(
            f"""
            SELECT id, topic, dedupe_key, payload_json, revision, attempt_count
            FROM outbox
            WHERE uploaded_at IS NULL
              AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
              {topic_filter}
            ORDER BY id
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [
            OutboxItem(
                id=int(row["id"]),
                topic=str(row["topic"]),
                dedupe_key=str(row["dedupe_key"]),
                payload=json.loads(row["payload_json"]),
                revision=int(row["revision"]),
                attempt_count=int(row["attempt_count"]),
            )
            for row in rows
        ]

    def mark_uploaded(self, items: Sequence[OutboxItem]) -> int:
        uploaded_at = isoformat_utc(utc_now())
        updated = 0
        with self._connection:
            for item in items:
                cursor = self._connection.execute(
                    """
                    UPDATE outbox
                    SET uploaded_at = ?,
                        last_error = NULL,
                        next_attempt_at = NULL,
                        updated_at = ?
                    WHERE id = ? AND revision = ?
                    """,
                    (uploaded_at, uploaded_at, item.id, item.revision),
                )
                updated += cursor.rowcount
        return updated

    def mark_failed(
        self,
        items: Sequence[OutboxItem],
        *,
        error: str,
        retry_at: str,
    ) -> int:
        updated_at = isoformat_utc(utc_now())
        updated = 0
        with self._connection:
            for item in items:
                cursor = self._connection.execute(
                    """
                    UPDATE outbox
                    SET attempt_count = attempt_count + 1,
                        last_error = ?,
                        next_attempt_at = ?,
                        updated_at = ?
                    WHERE id = ? AND revision = ? AND uploaded_at IS NULL
                    """,
                    (error[:2000], retry_at, updated_at, item.id, item.revision),
                )
                updated += cursor.rowcount
        return updated

    def status(self) -> StoreStatus:
        def count(table: str) -> int:
            row = self._connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            assert row is not None
            return int(row["count"])

        pending = self.pending_upload_count()
        failed = self.failed_upload_count()
        pending_raw = self.pending_upload_count((REMOTE_RAW_EVENTS,))
        failed_raw = self.failed_upload_count((REMOTE_RAW_EVENTS,))
        projection_topics = (REMOTE_SESSIONS, REMOTE_PHASES, REMOTE_SHOTS)
        return StoreStatus(
            raw_events=count("raw_events"),
            shots=count("shots"),
            sessions=count("sessions"),
            phases=count("phases"),
            pending_uploads=pending,
            failed_uploads=failed,
            pending_raw_uploads=pending_raw,
            failed_raw_uploads=failed_raw,
            pending_projection_uploads=self.pending_upload_count(projection_topics),
            failed_projection_uploads=self.failed_upload_count(projection_topics),
        )

    def pending_upload_count(self, topics: Sequence[str] | None = None) -> int:
        return self._outbox_count(topics=topics, failed_only=False)

    def failed_upload_count(self, topics: Sequence[str] | None = None) -> int:
        return self._outbox_count(topics=topics, failed_only=True)

    def projection_cursor(self, name: str) -> ProjectionCursor | None:
        row = self._connection.execute(
            """
            SELECT last_ingest_id, processed_events, normalizer_version
            FROM projection_cursors
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
        if row is None:
            return None
        return ProjectionCursor(
            last_ingest_id=int(row["last_ingest_id"]),
            processed_events=int(row["processed_events"]),
            normalizer_version=str(row["normalizer_version"]),
        )

    def save_projection_cursor(
        self,
        *,
        name: str,
        last_ingest_id: int,
        processed_events: int,
        normalizer_version: str,
    ) -> None:
        if last_ingest_id < 0:
            raise ValueError("last_ingest_id must not be negative")
        if processed_events < 0:
            raise ValueError("processed_events must not be negative")
        now = isoformat_utc(utc_now())
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO projection_cursors (
                    name,
                    last_ingest_id,
                    processed_events,
                    normalizer_version,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (name) DO UPDATE SET
                    last_ingest_id = excluded.last_ingest_id,
                    processed_events = excluded.processed_events,
                    normalizer_version = excluded.normalizer_version,
                    updated_at = excluded.updated_at
                """,
                (
                    name,
                    last_ingest_id,
                    processed_events,
                    normalizer_version,
                    now,
                ),
            )

    def _outbox_count(
        self,
        *,
        topics: Sequence[str] | None,
        failed_only: bool,
    ) -> int:
        clauses = ["uploaded_at IS NULL"]
        parameters: list[object] = []
        if failed_only:
            clauses.append("last_error IS NOT NULL")
        if topics:
            placeholders = ",".join("?" for _ in topics)
            clauses.append(f"topic IN ({placeholders})")
            parameters.extend(topics)
        row = self._connection.execute(
            f"SELECT COUNT(*) AS count FROM outbox WHERE {' AND '.join(clauses)}",
            parameters,
        ).fetchone()
        assert row is not None
        return int(row["count"])

    def _apply_assignment(
        self,
        *,
        cursor: sqlite3.Cursor,
        range_id: str,
        record: FramedRecord,
        raw_event_id: int,
        raw_event_key: str,
        shot: ShotMessage,
        shot_key: str,
        parsed_payload: dict[str, Any] | None,
        parser_version: str,
        assignment: ShotAssignment,
        previous_state: LaneState | None,
    ) -> None:
        now = isoformat_utc(utc_now())
        received_at = isoformat_utc(record.completed_at)
        previous_activity = (
            isoformat_utc(previous_state.last_activity_at) if previous_state else received_at
        )

        if assignment.close_phase_id:
            cursor.execute(
                """
                UPDATE phases
                SET ended_at = COALESCE(ended_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (previous_activity, now, assignment.close_phase_id),
            )
        if assignment.close_session_id:
            cursor.execute(
                """
                UPDATE sessions
                SET ended_at = COALESCE(ended_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (previous_activity, now, assignment.close_session_id),
            )

        if assignment.new_session:
            cursor.execute(
                """
                INSERT INTO sessions (
                    id,
                    range_id,
                    lane_number,
                    firing_point_index,
                    shooter_number,
                    started_at,
                    last_activity_at,
                    ended_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    assignment.session_id,
                    range_id,
                    shot.lane_number,
                    shot.firing_point_index,
                    shot.shooter_number,
                    received_at,
                    received_at,
                    now,
                ),
            )
        else:
            cursor.execute(
                """
                UPDATE sessions
                SET last_activity_at = ?,
                    firing_point_index = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    received_at,
                    shot.firing_point_index,
                    now,
                    assignment.session_id,
                ),
            )

        if assignment.new_phase:
            cursor.execute(
                """
                INSERT INTO phases (
                    id,
                    session_id,
                    range_id,
                    lane_number,
                    phase_kind,
                    ordinal,
                    started_at,
                    last_activity_at,
                    ended_at,
                    shot_count,
                    score_sum_tenths,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 0, ?)
                """,
                (
                    assignment.phase_id,
                    assignment.session_id,
                    range_id,
                    shot.lane_number,
                    assignment.phase_kind.value,
                    assignment.phase_ordinal,
                    received_at,
                    received_at,
                    now,
                ),
            )

        cursor.execute(
            """
            UPDATE phases
            SET last_activity_at = ?,
                shot_count = shot_count + 1,
                score_sum_tenths = score_sum_tenths + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (received_at, shot.score_tenths, now, assignment.phase_id),
        )
        cursor.execute(
            """
            UPDATE sessions
            SET last_activity_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (received_at, now, assignment.session_id),
        )

        cursor.execute(
            """
            INSERT INTO shots (
                shot_key,
                raw_event_id,
                raw_event_key,
                session_id,
                phase_id,
                range_id,
                lane_number,
                firing_point_index,
                shooter_number,
                received_at,
                device_time_text,
                annual_ticks,
                event_sequence,
                phase_kind,
                shot_number,
                score_integer,
                score_tenths,
                primary_score_raw,
                secondary_score_raw,
                shot_flags_raw,
                exercise_code_raw,
                x_native,
                y_native,
                parser_version,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shot_key,
                raw_event_id,
                raw_event_key,
                assignment.session_id,
                assignment.phase_id,
                range_id,
                shot.lane_number,
                shot.firing_point_index,
                shot.shooter_number,
                received_at,
                shot.device_time_text,
                shot.annual_ticks,
                shot.event_sequence,
                shot.shot_kind.value,
                shot.shot_number,
                shot.integer_score,
                shot.score_tenths,
                shot.primary_score_raw,
                shot.secondary_score_raw,
                shot.shot_flags_raw,
                shot.exercise_code_raw,
                str(shot.x_native),
                str(shot.y_native),
                parser_version,
                _json_dumps(parsed_payload),
            ),
        )
        self._upsert_lane_state(cursor, assignment.next_state)

        changed_sessions = {assignment.session_id}
        changed_phases = {assignment.phase_id}
        if assignment.close_session_id:
            changed_sessions.add(assignment.close_session_id)
        if assignment.close_phase_id:
            changed_phases.add(assignment.close_phase_id)

        for session_id in changed_sessions:
            self._enqueue_snapshot(
                cursor,
                table="sessions",
                topic=REMOTE_SESSIONS,
                record_id=session_id,
                payload_factory=_session_payload,
            )
        for phase_id in changed_phases:
            self._enqueue_snapshot(
                cursor,
                table="phases",
                topic=REMOTE_PHASES,
                record_id=phase_id,
                payload_factory=_phase_payload,
            )

        self._enqueue(
            cursor,
            topic=REMOTE_SHOTS,
            dedupe_key=shot_key,
            payload={
                "shot_key": shot_key,
                "raw_event_key": raw_event_key,
                "session_id": assignment.session_id,
                "phase_id": assignment.phase_id,
                "range_id": range_id,
                "lane_number": shot.lane_number,
                "firing_point_index": shot.firing_point_index,
                "shooter_number": shot.shooter_number,
                "received_at": received_at,
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
                "parser_version": parser_version,
                "payload": parsed_payload,
            },
            coalesce=False,
        )

    def _load_lane_state(
        self,
        cursor: sqlite3.Cursor,
        *,
        range_id: str,
        lane_number: int,
    ) -> LaneState | None:
        row = cursor.execute(
            """
            SELECT *
            FROM lane_state
            WHERE range_id = ? AND lane_number = ?
            """,
            (range_id, lane_number),
        ).fetchone()
        if row is None:
            return None
        return LaneState(
            range_id=str(row["range_id"]),
            lane_number=int(row["lane_number"]),
            firing_point_index=int(row["firing_point_index"]),
            shooter_number=row["shooter_number"],
            session_id=str(row["session_id"]),
            phase_id=str(row["phase_id"]),
            phase_kind=ShotKind(row["phase_kind"]),
            last_shot_number=int(row["last_shot_number"]),
            last_shot_key=str(row["last_shot_key"]),
            last_annual_ticks=int(row["last_annual_ticks"]),
            last_activity_at=parse_utc(row["last_activity_at"]),
            match_ordinal=int(row["match_ordinal"]),
            sighter_ordinal=int(row["sighter_ordinal"]),
        )

    def _upsert_lane_state(self, cursor: sqlite3.Cursor, state: LaneState) -> None:
        cursor.execute(
            """
            INSERT INTO lane_state (
                range_id,
                lane_number,
                firing_point_index,
                shooter_number,
                session_id,
                phase_id,
                phase_kind,
                last_shot_number,
                last_shot_key,
                last_annual_ticks,
                last_activity_at,
                match_ordinal,
                sighter_ordinal
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (range_id, lane_number) DO UPDATE SET
                firing_point_index = excluded.firing_point_index,
                shooter_number = excluded.shooter_number,
                session_id = excluded.session_id,
                phase_id = excluded.phase_id,
                phase_kind = excluded.phase_kind,
                last_shot_number = excluded.last_shot_number,
                last_shot_key = excluded.last_shot_key,
                last_annual_ticks = excluded.last_annual_ticks,
                last_activity_at = excluded.last_activity_at,
                match_ordinal = excluded.match_ordinal,
                sighter_ordinal = excluded.sighter_ordinal
            """,
            (
                state.range_id,
                state.lane_number,
                state.firing_point_index,
                state.shooter_number,
                state.session_id,
                state.phase_id,
                state.phase_kind.value,
                state.last_shot_number,
                state.last_shot_key,
                state.last_annual_ticks,
                isoformat_utc(state.last_activity_at),
                state.match_ordinal,
                state.sighter_ordinal,
            ),
        )

    def _enqueue_snapshot(
        self,
        cursor: sqlite3.Cursor,
        *,
        table: str,
        topic: str,
        record_id: str,
        payload_factory: Callable[[sqlite3.Row], dict[str, object]],
    ) -> None:
        row = cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            return
        self._enqueue(
            cursor,
            topic=topic,
            dedupe_key=record_id,
            payload=payload_factory(row),
            coalesce=True,
        )

    def _enqueue(
        self,
        cursor: sqlite3.Cursor,
        *,
        topic: str,
        dedupe_key: str,
        payload: dict[str, object],
        coalesce: bool,
    ) -> None:
        now = isoformat_utc(utc_now())
        if coalesce:
            cursor.execute(
                """
                INSERT INTO outbox (
                    topic,
                    dedupe_key,
                    payload_json,
                    revision,
                    attempt_count,
                    next_attempt_at,
                    last_error,
                    uploaded_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, 1, 0, NULL, NULL, NULL, ?, ?)
                ON CONFLICT (topic, dedupe_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    revision = outbox.revision + 1,
                    attempt_count = 0,
                    next_attempt_at = NULL,
                    last_error = NULL,
                    uploaded_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (topic, dedupe_key, _json_dumps(payload), now, now),
            )
        else:
            cursor.execute(
                """
                INSERT OR IGNORE INTO outbox (
                    topic,
                    dedupe_key,
                    payload_json,
                    revision,
                    attempt_count,
                    next_attempt_at,
                    last_error,
                    uploaded_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, 1, 0, NULL, NULL, NULL, ?, ?)
                """,
                (topic, dedupe_key, _json_dumps(payload), now, now),
            )

    def _migrate(self) -> None:
        version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
            )
        if version == SCHEMA_VERSION:
            return

        with self._connection:
            if version < 1:
                self._connection.executescript(_SCHEMA_V1)
            if version < 2:
                self._connection.executescript(_SCHEMA_V2)
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _observation_key(record: FramedRecord, raw_hash: str) -> str:
    return _hash_key(str(record.connection_id), str(record.sequence), raw_hash)


def _shot_key(range_id: str, shot: ShotMessage, raw_hash: str) -> str:
    return _hash_key(
        range_id,
        "shot",
        str(shot.lane_number),
        str(shot.annual_ticks),
        str(shot.event_sequence),
        str(shot.shot_number),
        raw_hash,
    )


def _stable_event_key(
    *,
    range_id: str,
    message: ParsedMessage | None,
    message_type: str | None,
    raw_hash: str,
) -> str:
    if isinstance(message, ShotMessage):
        return _shot_key(range_id, message, raw_hash)
    if isinstance(message, GenericMessage) and message.event_sequence is not None:
        return _hash_key(
            range_id,
            message.record_type,
            str(message.lane_number),
            str(message.event_sequence),
            str(message.annual_ticks),
            raw_hash,
        )
    return _hash_key(range_id, message_type or "unknown", raw_hash)


def _hash_key(*parts: str) -> str:
    return sha256("\0".join(parts).encode()).hexdigest()


def _message_type(message: ParsedMessage | None, raw: bytes) -> str | None:
    if message is not None:
        return message.record_type
    prefix = raw.split(b";", 1)[0].decode("latin-1", errors="replace")
    return prefix or None


def _lane_number(message: ParsedMessage | None) -> int | None:
    if message is None:
        return None
    return message.lane_number


def _shooter_number(message: ParsedMessage | None) -> str | None:
    if message is None:
        return None
    return message.shooter_number


def _message_attribute(
    message: ParsedMessage | None,
    name: str,
) -> object | None:
    if message is None:
        return None
    return getattr(message, name, None)


def _result(
    *,
    observation_inserted: bool,
    message_type: str | None,
    parse_error: str | None,
    shot_inserted: bool = False,
    shot_duplicate: bool = False,
    shot_key: str | None = None,
    lane_number: int | None = None,
    shooter_number: str | None = None,
    shot_kind: ShotKind | None = None,
    shot_number: int | None = None,
    score_tenths: int | None = None,
    session_id: str | None = None,
    phase_id: str | None = None,
) -> IngestResult:
    return IngestResult(
        observation_inserted=observation_inserted,
        message_type=message_type,
        parse_error=parse_error,
        shot_inserted=shot_inserted,
        shot_duplicate=shot_duplicate,
        shot_key=shot_key,
        lane_number=lane_number,
        shooter_number=shooter_number,
        shot_kind=shot_kind,
        shot_number=shot_number,
        score_tenths=score_tenths,
        session_id=session_id,
        phase_id=phase_id,
    )


def _session_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "range_id": row["range_id"],
        "lane_number": row["lane_number"],
        "firing_point_index": row["firing_point_index"],
        "shooter_number": row["shooter_number"],
        "started_at": row["started_at"],
        "last_activity_at": row["last_activity_at"],
        "ended_at": row["ended_at"],
        "updated_at": row["updated_at"],
    }


def _phase_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "range_id": row["range_id"],
        "lane_number": row["lane_number"],
        "phase_kind": row["phase_kind"],
        "ordinal": row["ordinal"],
        "started_at": row["started_at"],
        "last_activity_at": row["last_activity_at"],
        "ended_at": row["ended_at"],
        "shot_count": row["shot_count"],
        "score_sum_tenths": row["score_sum_tenths"],
        "updated_at": row["updated_at"],
    }


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS raw_events (
    id INTEGER PRIMARY KEY,
    observation_key TEXT NOT NULL UNIQUE,
    stable_event_key TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    record_sequence INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    event_type TEXT,
    lane_number INTEGER,
    raw_bytes BLOB NOT NULL,
    delimiter_bytes BLOB NOT NULL,
    raw_sha256 TEXT NOT NULL,
    complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
    parser_version TEXT NOT NULL,
    parsed_json TEXT,
    parse_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS raw_events_stable_event_key_idx
    ON raw_events (stable_event_key);
CREATE INDEX IF NOT EXISTS raw_events_lane_received_idx
    ON raw_events (lane_number, received_at);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    range_id TEXT NOT NULL,
    lane_number INTEGER NOT NULL,
    firing_point_index INTEGER NOT NULL,
    shooter_number TEXT,
    started_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    ended_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_range_shooter_idx
    ON sessions (range_id, shooter_number, started_at);

CREATE TABLE IF NOT EXISTS phases (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    range_id TEXT NOT NULL,
    lane_number INTEGER NOT NULL,
    phase_kind TEXT NOT NULL CHECK (phase_kind IN ('sighter', 'match')),
    ordinal INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    ended_at TEXT,
    shot_count INTEGER NOT NULL DEFAULT 0,
    score_sum_tenths INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE (session_id, phase_kind, ordinal)
);

CREATE TABLE IF NOT EXISTS shots (
    shot_key TEXT PRIMARY KEY,
    raw_event_id INTEGER NOT NULL UNIQUE REFERENCES raw_events (id),
    raw_event_key TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    phase_id TEXT NOT NULL REFERENCES phases (id),
    range_id TEXT NOT NULL,
    lane_number INTEGER NOT NULL,
    firing_point_index INTEGER NOT NULL,
    shooter_number TEXT,
    received_at TEXT NOT NULL,
    device_time_text TEXT NOT NULL,
    annual_ticks INTEGER NOT NULL,
    event_sequence INTEGER NOT NULL,
    phase_kind TEXT NOT NULL CHECK (phase_kind IN ('sighter', 'match')),
    shot_number INTEGER NOT NULL,
    score_integer INTEGER NOT NULL,
    score_tenths INTEGER NOT NULL,
    primary_score_raw INTEGER NOT NULL,
    secondary_score_raw INTEGER NOT NULL,
    shot_flags_raw INTEGER NOT NULL,
    exercise_code_raw INTEGER NOT NULL,
    x_native TEXT NOT NULL,
    y_native TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS shots_session_phase_idx
    ON shots (session_id, phase_id, shot_number);
CREATE INDEX IF NOT EXISTS shots_range_lane_received_idx
    ON shots (range_id, lane_number, received_at);

CREATE TABLE IF NOT EXISTS lane_state (
    range_id TEXT NOT NULL,
    lane_number INTEGER NOT NULL,
    firing_point_index INTEGER NOT NULL,
    shooter_number TEXT,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    phase_id TEXT NOT NULL REFERENCES phases (id),
    phase_kind TEXT NOT NULL CHECK (phase_kind IN ('sighter', 'match')),
    last_shot_number INTEGER NOT NULL,
    last_shot_key TEXT NOT NULL,
    last_annual_ticks INTEGER NOT NULL,
    last_activity_at TEXT NOT NULL,
    match_ordinal INTEGER NOT NULL,
    sighter_ordinal INTEGER NOT NULL,
    PRIMARY KEY (range_id, lane_number)
);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    topic TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    uploaded_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (topic, dedupe_key)
);
CREATE INDEX IF NOT EXISTS outbox_pending_idx
    ON outbox (uploaded_at, next_attempt_at, id);
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS projection_cursors (
    name TEXT PRIMARY KEY,
    last_ingest_id INTEGER NOT NULL,
    processed_events INTEGER NOT NULL,
    normalizer_version TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
