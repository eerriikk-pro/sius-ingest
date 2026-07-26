import unittest
from hashlib import sha256

from sius_ingest.keys import shot_key
from sius_ingest.models import LaneState, ShotKind, ShotMessage
from sius_ingest.parser import ProtocolParser
from sius_ingest.projection import ProjectionBuilder
from sius_ingest.remote_source import RemoteRawEvent
from sius_ingest.time_utils import parse_utc
from tests.helpers import framed_record, shot_line


def remote_shot(
    ingest_id: int,
    *,
    flags: int,
    number: int,
    annual_ticks: int,
    seconds: int = 0,
) -> RemoteRawEvent:
    record = framed_record(
        shot_line(
            event_sequence=ingest_id,
            shot_flags=flags,
            score_tenths=90 + ingest_id,
            shot_number=number,
            annual_ticks=annual_ticks,
        ),
        sequence=ingest_id,
        seconds=seconds,
    )
    message = ProtocolParser().parse(record.raw)
    assert isinstance(message, ShotMessage)
    canonical_key = shot_key(
        "range-a",
        message,
        sha256(record.raw + record.delimiter).hexdigest(),
    )
    return RemoteRawEvent(
        ingest_id=ingest_id,
        event_key=f"event-{ingest_id}",
        stable_event_key=canonical_key,
        range_id="range-a",
        event_type="_SHOT",
        record=record,
    )


def state_from_page(page) -> LaneState:
    row = page.lane_states[0]
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


class ProjectionBuilderTests(unittest.TestCase):
    def test_segments_controlled_sighter_and_match_sequence(self) -> None:
        events = [
            remote_shot(1, flags=39, number=1, annual_ticks=1001),
            remote_shot(2, flags=7, number=1, annual_ticks=1002, seconds=1),
            remote_shot(3, flags=7, number=2, annual_ticks=1003, seconds=2),
            remote_shot(4, flags=39, number=1, annual_ticks=1004, seconds=3),
            remote_shot(5, flags=7, number=1, annual_ticks=1005, seconds=4),
        ]

        page = ProjectionBuilder(
            lane_states={},
            existing_shot_keys=set(),
        ).build(events)

        self.assertEqual(page.parsed_shots, 5)
        self.assertEqual(len(page.session_starts), 1)
        self.assertEqual(
            [(row["phase_kind"], row["ordinal"]) for row in page.phase_starts],
            [("sighter", 1), ("match", 1), ("sighter", 2), ("match", 2)],
        )
        self.assertEqual(len(page.phase_closures), 3)
        self.assertEqual(state_from_page(page).match_ordinal, 2)

    def test_duplicate_within_page_is_not_projected_twice(self) -> None:
        event = remote_shot(1, flags=7, number=1, annual_ticks=1001)

        page = ProjectionBuilder(
            lane_states={},
            existing_shot_keys=set(),
        ).build([event, event])

        self.assertEqual(page.parsed_shots, 1)
        self.assertEqual(page.duplicate_shots, 1)
        self.assertEqual(len(page.shots), 1)

    def test_malformed_record_is_recorded_without_blocking_page(self) -> None:
        malformed_record = framed_record(b"_SHOT;broken", sequence=1)
        malformed = RemoteRawEvent(
            ingest_id=1,
            event_key="event-1",
            stable_event_key="stable-1",
            range_id="range-a",
            event_type="_SHOT",
            record=malformed_record,
        )
        valid = remote_shot(2, flags=7, number=1, annual_ticks=1002, seconds=1)

        page = ProjectionBuilder(
            lane_states={},
            existing_shot_keys=set(),
        ).build([malformed, valid])

        self.assertEqual(page.processed_events, 2)
        self.assertEqual(page.parse_errors, 1)
        self.assertEqual(page.parsed_shots, 1)
        self.assertEqual(page.errors[0]["error_kind"], "parse_error")

    def test_out_of_order_shot_is_quarantined_without_state_regression(self) -> None:
        current_event = remote_shot(
            1,
            flags=7,
            number=2,
            annual_ticks=2000,
            seconds=10,
        )
        first_page = ProjectionBuilder(
            lane_states={},
            existing_shot_keys=set(),
        ).build([current_event])
        current_state = state_from_page(first_page)
        late_event = remote_shot(
            2,
            flags=7,
            number=1,
            annual_ticks=1000,
            seconds=5,
        )

        page = ProjectionBuilder(
            lane_states={("range-a", 6): current_state},
            existing_shot_keys=set(),
        ).build([late_event])

        self.assertEqual(page.parsed_shots, 0)
        self.assertEqual(page.quarantined_shots, 1)
        self.assertEqual(page.errors[0]["error_kind"], "out_of_order_shot")
        self.assertEqual(state_from_page(page), current_state)


if __name__ == "__main__":
    unittest.main()
