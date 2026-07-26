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
