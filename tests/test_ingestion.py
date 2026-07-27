import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sius_ingest.ingest import IngestionConfig, IngestionService
from sius_ingest.outbox import SQLiteEventStore
from tests.helpers import framed_record, shot_line


class IngestionServiceTests(unittest.TestCase):
    def test_raw_only_mode_does_not_build_or_queue_projections(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "sius.sqlite3"
            with SQLiteEventStore(database) as store:
                service = IngestionService(
                    store=store,
                    config=IngestionConfig(
                        range_id="range-a",
                        project_locally=False,
                        enqueue_raw_upload=True,
                    ),
                )
                result = service.process(
                    framed_record(
                        shot_line(
                            event_sequence=1,
                            shot_flags=7,
                            score_tenths=94,
                            shot_number=1,
                            annual_ticks=1001,
                        ),
                        sequence=1,
                    )
                )
                status = store.status()

        self.assertTrue(result.observation_inserted)
        self.assertFalse(result.shot_inserted)
        self.assertEqual(result.score_tenths, 94)
        self.assertEqual(status.raw_events, 1)
        self.assertEqual(status.shots, 0)
        self.assertEqual(status.sessions, 0)
        self.assertEqual(status.phases, 0)
        self.assertEqual(status.pending_raw_uploads, 1)
        self.assertEqual(status.pending_projection_uploads, 0)

    def test_raw_only_mode_suppresses_a_shot_replayed_on_a_new_connection(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "sius.sqlite3"
            with SQLiteEventStore(database) as store:
                service = IngestionService(
                    store=store,
                    config=IngestionConfig(
                        range_id="range-a",
                        project_locally=False,
                        enqueue_raw_upload=True,
                    ),
                )
                raw = shot_line(
                    event_sequence=8,
                    shot_flags=7,
                    score_tenths=99,
                    shot_number=3,
                    annual_ticks=1008,
                )
                original = service.process(framed_record(raw, sequence=8))
                replay = service.process(
                    framed_record(
                        raw,
                        sequence=1,
                        connection_id=UUID("00000000-0000-0000-0000-000000000002"),
                    )
                )
                status = store.status()

        self.assertTrue(original.observation_inserted)
        self.assertFalse(replay.observation_inserted)
        self.assertTrue(replay.shot_duplicate)
        self.assertEqual(status.raw_events, 1)
        self.assertEqual(status.pending_raw_uploads, 1)

    def test_raw_only_mode_only_suppresses_generic_events_with_stable_counters(self) -> None:
        diagnostic = b"_DIAG;5;6;0;60;12;17:15:20.46;11;0;0;1768803440"
        stateless_total = b"_TOTL;5;6;0;103;T;0;0;Q;0;0;S;0;0;"
        second_connection = UUID("00000000-0000-0000-0000-000000000002")

        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "sius.sqlite3"
            with SQLiteEventStore(database) as store:
                service = IngestionService(
                    store=store,
                    config=IngestionConfig(
                        range_id="range-a",
                        project_locally=False,
                        enqueue_raw_upload=True,
                    ),
                )
                diagnostic_original = service.process(framed_record(diagnostic, sequence=1))
                diagnostic_replay = service.process(
                    framed_record(
                        diagnostic,
                        sequence=1,
                        connection_id=second_connection,
                    )
                )
                total_original = service.process(framed_record(stateless_total, sequence=2))
                total_repeat = service.process(
                    framed_record(
                        stateless_total,
                        sequence=2,
                        connection_id=second_connection,
                    )
                )
                status = store.status()

        self.assertTrue(diagnostic_original.observation_inserted)
        self.assertFalse(diagnostic_replay.observation_inserted)
        self.assertTrue(total_original.observation_inserted)
        self.assertTrue(total_repeat.observation_inserted)
        self.assertEqual(status.raw_events, 3)
        self.assertEqual(status.pending_raw_uploads, 3)

    def test_persists_deduplicates_and_segments_controlled_sequence(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "sius.sqlite3"
            with SQLiteEventStore(database) as store:
                service = IngestionService(
                    store=store,
                    config=IngestionConfig(range_id="range-a"),
                )
                records = [
                    framed_record(
                        shot_line(
                            event_sequence=1,
                            shot_flags=39,
                            score_tenths=96,
                            shot_number=1,
                            annual_ticks=1001,
                        ),
                        sequence=1,
                    ),
                    framed_record(
                        shot_line(
                            event_sequence=2,
                            shot_flags=7,
                            score_tenths=94,
                            shot_number=1,
                            annual_ticks=1002,
                        ),
                        sequence=2,
                        seconds=1,
                    ),
                    framed_record(
                        shot_line(
                            event_sequence=3,
                            shot_flags=7,
                            score_tenths=92,
                            shot_number=2,
                            annual_ticks=1003,
                        ),
                        sequence=3,
                        seconds=2,
                    ),
                    framed_record(
                        shot_line(
                            event_sequence=4,
                            shot_flags=39,
                            score_tenths=85,
                            shot_number=1,
                            annual_ticks=1004,
                        ),
                        sequence=4,
                        seconds=3,
                    ),
                    framed_record(
                        shot_line(
                            event_sequence=5,
                            shot_flags=7,
                            score_tenths=73,
                            shot_number=1,
                            annual_ticks=1005,
                        ),
                        sequence=5,
                        seconds=4,
                    ),
                ]
                results = [service.process(record) for record in records]

                duplicate = framed_record(
                    records[-1].raw,
                    sequence=1,
                    seconds=5,
                    connection_id=UUID("00000000-0000-0000-0000-000000000002"),
                )
                duplicate_result = service.process(duplicate)
                status = store.status()

            self.assertTrue(all(result.shot_inserted for result in results))
            self.assertTrue(duplicate_result.shot_duplicate)
            self.assertEqual(status.raw_events, 6)
            self.assertEqual(status.shots, 5)
            self.assertEqual(status.sessions, 1)
            self.assertEqual(status.phases, 4)
            self.assertEqual(status.pending_uploads, 16)

            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            phases = connection.execute(
                """
                SELECT phase_kind, ordinal, shot_count, score_sum_tenths
                FROM phases
                ORDER BY started_at
                """
            ).fetchall()
            connection.close()

        self.assertEqual(
            [tuple(row) for row in phases],
            [
                ("sighter", 1, 1, 96),
                ("match", 1, 2, 186),
                ("sighter", 2, 1, 85),
                ("match", 2, 1, 73),
            ],
        )

    def test_preserves_parse_errors_without_losing_raw_record(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "sius.sqlite3"
            with SQLiteEventStore(database) as store:
                service = IngestionService(
                    store=store,
                    config=IngestionConfig(range_id="range-a"),
                )
                result = service.process(framed_record(b"_SHOT;broken", sequence=1))
                status = store.status()

        self.assertIsNotNone(result.parse_error)
        self.assertEqual(status.raw_events, 1)
        self.assertEqual(status.shots, 0)


if __name__ == "__main__":
    unittest.main()
