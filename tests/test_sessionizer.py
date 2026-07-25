import unittest
from datetime import timedelta

from sius_ingest.models import SessionizerConfig, ShotKind, ShotMessage
from sius_ingest.parser import ProtocolParser
from sius_ingest.sessionizer import RelaySessionizer
from tests.helpers import BASE_TIME, shot_line


class RelaySessionizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ProtocolParser()
        self.sessionizer = RelaySessionizer()

    def shot(
        self,
        *,
        event_sequence: int,
        flags: int,
        number: int,
        shooter: str = "123",
        annual_ticks: int | None = None,
    ) -> ShotMessage:
        message = self.parser.parse(
            shot_line(
                shooter=shooter,
                event_sequence=event_sequence,
                shot_flags=flags,
                score_tenths=90,
                shot_number=number,
                annual_ticks=(annual_ticks if annual_ticks is not None else 1000 + event_sequence),
            )
        )
        assert isinstance(message, ShotMessage)
        return message

    def test_segments_sighters_and_open_ended_match_relays(self) -> None:
        first = self.sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=1, flags=7, number=1),
            shot_key="shot-1",
            received_at=BASE_TIME,
            state=None,
        )
        second = self.sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=2, flags=7, number=2),
            shot_key="shot-2",
            received_at=BASE_TIME + timedelta(seconds=1),
            state=first.next_state,
        )
        sighter = self.sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=3, flags=39, number=1),
            shot_key="shot-3",
            received_at=BASE_TIME + timedelta(seconds=2),
            state=second.next_state,
        )
        next_match = self.sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=4, flags=7, number=1),
            shot_key="shot-4",
            received_at=BASE_TIME + timedelta(seconds=3),
            state=sighter.next_state,
        )

        self.assertTrue(first.new_session)
        self.assertTrue(first.new_phase)
        self.assertEqual(first.phase_kind, ShotKind.MATCH)
        self.assertEqual(first.phase_ordinal, 1)
        self.assertFalse(second.new_phase)
        self.assertTrue(sighter.new_phase)
        self.assertEqual(sighter.close_phase_id, first.phase_id)
        self.assertEqual(sighter.phase_ordinal, 1)
        self.assertTrue(next_match.new_phase)
        self.assertEqual(next_match.phase_ordinal, 2)
        self.assertEqual(next_match.session_id, first.session_id)

    def test_counter_restart_starts_match_relay_without_sighters(self) -> None:
        first = self.sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=1, flags=7, number=1),
            shot_key="shot-1",
            received_at=BASE_TIME,
            state=None,
        )
        second = self.sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=2, flags=7, number=2),
            shot_key="shot-2",
            received_at=BASE_TIME + timedelta(seconds=1),
            state=first.next_state,
        )
        restarted = self.sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=10, flags=7, number=1),
            shot_key="shot-10",
            received_at=BASE_TIME + timedelta(seconds=10),
            state=second.next_state,
        )

        self.assertTrue(restarted.new_phase)
        self.assertEqual(restarted.phase_kind, ShotKind.MATCH)
        self.assertEqual(restarted.phase_ordinal, 2)

    def test_shooter_change_starts_new_session(self) -> None:
        first = self.sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=1, flags=39, number=1),
            shot_key="shot-1",
            received_at=BASE_TIME,
            state=None,
        )
        changed = self.sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=2, flags=39, number=1, shooter="456"),
            shot_key="shot-2",
            received_at=BASE_TIME + timedelta(seconds=1),
            state=first.next_state,
        )

        self.assertTrue(changed.new_session)
        self.assertEqual(changed.close_session_id, first.session_id)
        self.assertNotEqual(changed.session_id, first.session_id)

    def test_idle_timeout_starts_new_session(self) -> None:
        sessionizer = RelaySessionizer(SessionizerConfig(session_timeout=timedelta(minutes=30)))
        first = sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=1, flags=7, number=1),
            shot_key="shot-1",
            received_at=BASE_TIME,
            state=None,
        )
        later = sessionizer.assign(
            range_id="range-a",
            shot=self.shot(event_sequence=2, flags=7, number=2),
            shot_key="shot-2",
            received_at=BASE_TIME + timedelta(minutes=31),
            state=first.next_state,
        )

        self.assertTrue(later.new_session)

    def test_device_counter_detects_idle_gap_in_fast_backlog(self) -> None:
        sessionizer = RelaySessionizer(SessionizerConfig(session_timeout=timedelta(minutes=30)))
        first = sessionizer.assign(
            range_id="range-a",
            shot=self.shot(
                event_sequence=1,
                flags=7,
                number=1,
                annual_ticks=1_000_000,
            ),
            shot_key="shot-1",
            received_at=BASE_TIME,
            state=None,
        )
        later = sessionizer.assign(
            range_id="range-a",
            shot=self.shot(
                event_sequence=2,
                flags=7,
                number=1,
                annual_ticks=1_000_000 + (30 * 60 * 100) + 1,
            ),
            shot_key="shot-2",
            received_at=BASE_TIME + timedelta(seconds=1),
            state=first.next_state,
        )

        self.assertTrue(later.new_session)


if __name__ == "__main__":
    unittest.main()
