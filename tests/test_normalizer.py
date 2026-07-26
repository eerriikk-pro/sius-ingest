import unittest
from hashlib import sha256

from sius_ingest.keys import shot_key
from sius_ingest.models import LaneState, ShotKind, ShotMessage
from sius_ingest.normalizer import NORMALIZER_VERSION, SupabaseNormalizer
from sius_ingest.parser import ProtocolParser
from sius_ingest.remote_projection import (
    ProjectionCommitSummary,
    RemoteProjectionConflict,
    RemoteProjectionState,
)
from sius_ingest.remote_source import RemoteRawEvent
from sius_ingest.time_utils import parse_utc
from tests.helpers import framed_record, shot_line


class FakeSource:
    def __init__(self, events: list[RemoteRawEvent]) -> None:
        self.events = events
        self.requested_after: list[int] = []

    def fetch_after(
        self,
        last_ingest_id: int,
        *,
        limit: int,
    ) -> list[RemoteRawEvent]:
        self.requested_after.append(last_ingest_id)
        return [event for event in self.events if event.ingest_id > last_ingest_id][:limit]


class FakeRepository:
    def __init__(self, *, conflict_once: bool = False) -> None:
        self.state = RemoteProjectionState(
            last_ingest_id=0,
            processed_events=0,
            normalizer_version=NORMALIZER_VERSION,
            lane_states={},
        )
        self.shot_keys: set[str] = set()
        self.pages = []
        self.conflict_once = conflict_once
        self.successes = 0

    def load_state(self, *, projection_name, normalizer_version):
        if normalizer_version != NORMALIZER_VERSION:
            raise AssertionError("unexpected version")
        return self.state

    def existing_shot_keys(self, shot_keys):
        return self.shot_keys.intersection(shot_keys)

    def mark_success(self, *, projection_name, normalizer_version):
        self.successes += 1

    def commit_page(
        self,
        *,
        projection_name,
        normalizer_version,
        expected_last_ingest_id,
        next_last_ingest_id,
        page,
    ):
        if self.conflict_once:
            self.conflict_once = False
            raise RemoteProjectionConflict("projection checkpoint conflict")
        if expected_last_ingest_id != self.state.last_ingest_id:
            raise AssertionError("stale checkpoint")
        self.pages.append(page)
        self.shot_keys.update(row["shot_key"] for row in page.shots)
        lane_states = {
            (str(row["range_id"]), int(row["lane_number"])): _lane_state(row)
            for row in page.lane_states
        }
        self.state = RemoteProjectionState(
            last_ingest_id=next_last_ingest_id,
            processed_events=self.state.processed_events + page.processed_events,
            normalizer_version=NORMALIZER_VERSION,
            lane_states=lane_states,
        )
        return ProjectionCommitSummary(
            last_ingest_id=next_last_ingest_id,
            processed_events=self.state.processed_events,
            committed_shots=len(page.shots),
            recorded_errors=len(page.errors),
        )


def _event(
    ingest_id: int,
    *,
    flags: int,
    shot_number: int,
    annual_ticks: int,
    seconds: int = 0,
) -> RemoteRawEvent:
    record = framed_record(
        shot_line(
            event_sequence=ingest_id,
            shot_flags=flags,
            score_tenths=90 + ingest_id,
            shot_number=shot_number,
            annual_ticks=annual_ticks,
        ),
        sequence=ingest_id,
        seconds=seconds,
    )
    message = ProtocolParser().parse(record.raw)
    assert isinstance(message, ShotMessage)
    raw_hash = sha256(record.raw + record.delimiter).hexdigest()
    canonical_key = shot_key("range-a", message, raw_hash)
    return RemoteRawEvent(
        ingest_id=ingest_id,
        event_key=f"event-{ingest_id}",
        stable_event_key=canonical_key,
        range_id="range-a",
        event_type="_SHOT",
        record=record,
    )


def _lane_state(row):
    return LaneState(
        range_id=str(row["range_id"]),
        lane_number=int(row["lane_number"]),
        firing_point_index=int(row["firing_point_index"]),
        shooter_number=row["shooter_number"],
        session_id=str(row["session_id"]),
        phase_id=str(row["phase_id"]),
        phase_kind=ShotKind(str(row["phase_kind"])),
        last_shot_number=int(row["last_shot_number"]),
        last_shot_key=str(row["last_shot_key"]),
        last_annual_ticks=int(row["last_annual_ticks"]),
        last_activity_at=parse_utc(str(row["last_activity_at"])),
        match_ordinal=int(row["match_ordinal"]),
        sighter_ordinal=int(row["sighter_ordinal"]),
    )


class SupabaseNormalizerTests(unittest.TestCase):
    def test_processes_only_events_after_remote_checkpoint(self) -> None:
        events = [
            _event(1, flags=39, shot_number=1, annual_ticks=1001),
            _event(2, flags=7, shot_number=1, annual_ticks=1002, seconds=1),
        ]
        source = FakeSource(events)
        repository = FakeRepository()
        normalizer = SupabaseNormalizer(
            source=source,
            repository=repository,
            page_size=1,
        )

        first = normalizer.normalize_available()
        second = normalizer.normalize_available()

        self.assertEqual(first.fetched_events, 2)
        self.assertEqual(first.committed_shots, 2)
        self.assertEqual(first.last_ingest_id, 2)
        self.assertEqual(second.fetched_events, 0)
        self.assertEqual(source.requested_after, [0, 1, 2, 2])
        self.assertEqual(repository.successes, 2)

    def test_reloads_remote_state_after_checkpoint_conflict(self) -> None:
        source = FakeSource([_event(1, flags=7, shot_number=1, annual_ticks=1001)])
        repository = FakeRepository(conflict_once=True)
        normalizer = SupabaseNormalizer(source=source, repository=repository)

        summary = normalizer.normalize_available()

        self.assertEqual(summary.fetched_events, 1)
        self.assertEqual(summary.last_ingest_id, 1)
        self.assertEqual(len(repository.pages), 1)

    def test_existing_shot_does_not_advance_lane_state_twice(self) -> None:
        event = _event(1, flags=7, shot_number=1, annual_ticks=1001)
        repository = FakeRepository()
        repository.shot_keys.add(event.stable_event_key)
        normalizer = SupabaseNormalizer(
            source=FakeSource([event]),
            repository=repository,
        )

        summary = normalizer.normalize_available()

        self.assertEqual(summary.duplicate_shots, 1)
        self.assertEqual(summary.committed_shots, 0)
        self.assertEqual(repository.state.lane_states, {})


if __name__ == "__main__":
    unittest.main()
