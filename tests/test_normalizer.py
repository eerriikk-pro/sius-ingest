import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError

from sius_ingest.normalizer import (
    NORMALIZER_VERSION,
    NormalizationError,
    SupabaseNormalizer,
)
from sius_ingest.outbox import (
    REMOTE_PHASES,
    REMOTE_SESSIONS,
    REMOTE_SHOTS,
    SQLiteEventStore,
)
from sius_ingest.remote_source import RemoteRawEvent
from sius_ingest.uploader import SupabaseConfig, SupabaseUploader
from tests.helpers import framed_record, shot_line


class FakeResponse:
    status = 201

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _: int = -1) -> bytes:
        return b""


class FakeSource:
    def __init__(self, events: list[RemoteRawEvent]) -> None:
        self._events = events

    def fetch_after(
        self,
        last_ingest_id: int,
        *,
        limit: int,
    ) -> list[RemoteRawEvent]:
        return [event for event in self._events if event.ingest_id > last_ingest_id][:limit]


class SupabaseNormalizerTests(unittest.TestCase):
    def test_does_not_advance_cursor_until_projection_upload_succeeds(self) -> None:
        event = RemoteRawEvent(
            ingest_id=1,
            event_key="raw-event-1",
            range_id="range-a",
            record=framed_record(
                shot_line(
                    event_sequence=1,
                    shot_flags=7,
                    score_tenths=94,
                    shot_number=1,
                    annual_ticks=1001,
                ),
                sequence=1,
            ),
        )

        def fail_request(request, *, timeout):
            raise URLError("offline")

        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "normalizer.sqlite3"
            with SQLiteEventStore(database) as store:
                uploader = SupabaseUploader(
                    store=store,
                    config=SupabaseConfig(
                        url="https://example.supabase.co",
                        api_key="sb_secret_test",
                    ),
                    topics=(REMOTE_SESSIONS, REMOTE_PHASES, REMOTE_SHOTS),
                    http_open=fail_request,
                )
                normalizer = SupabaseNormalizer(
                    store=store,
                    source=FakeSource([event]),
                    uploader=uploader,
                )

                with self.assertRaises(NormalizationError):
                    normalizer.normalize_available()

                self.assertIsNone(store.projection_cursor("default"))
                self.assertEqual(store.status().pending_projection_uploads, 3)

    def test_projects_raw_events_and_advances_cursor_after_upload(self) -> None:
        events = [
            RemoteRawEvent(
                ingest_id=1,
                event_key="raw-event-1",
                range_id="range-a",
                record=framed_record(
                    shot_line(
                        event_sequence=1,
                        shot_flags=39,
                        score_tenths=96,
                        shot_number=1,
                        annual_ticks=1001,
                    ),
                    sequence=1,
                ),
            ),
            RemoteRawEvent(
                ingest_id=2,
                event_key="raw-event-2",
                range_id="range-a",
                record=framed_record(
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
            ),
        ]
        requests = []

        def open_request(request, *, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "normalizer.sqlite3"
            with SQLiteEventStore(database) as store:
                uploader = SupabaseUploader(
                    store=store,
                    config=SupabaseConfig(
                        url="https://example.supabase.co",
                        api_key="sb_secret_test",
                    ),
                    topics=(REMOTE_SESSIONS, REMOTE_PHASES, REMOTE_SHOTS),
                    http_open=open_request,
                )
                normalizer = SupabaseNormalizer(
                    store=store,
                    source=FakeSource(events),
                    uploader=uploader,
                )

                summary = normalizer.normalize_available()
                second_summary = normalizer.normalize_available()
                status = store.status()
                cursor = store.projection_cursor("default")

        self.assertEqual(summary.fetched_events, 2)
        self.assertEqual(summary.parsed_shots, 2)
        self.assertEqual(summary.parse_errors, 0)
        self.assertEqual(summary.last_ingest_id, 2)
        self.assertEqual(second_summary.fetched_events, 0)
        self.assertEqual(status.raw_events, 2)
        self.assertEqual(status.shots, 2)
        self.assertEqual(status.sessions, 1)
        self.assertEqual(status.phases, 2)
        self.assertEqual(status.pending_raw_uploads, 0)
        self.assertEqual(status.pending_projection_uploads, 0)
        assert cursor is not None
        self.assertEqual(cursor.last_ingest_id, 2)
        self.assertEqual(cursor.processed_events, 2)
        self.assertEqual(cursor.normalizer_version, NORMALIZER_VERSION)

        urls = [request.full_url for request, _ in requests]
        self.assertTrue(any("/sius_sessions?" in url for url in urls))
        self.assertTrue(any("/sius_phases?" in url for url in urls))
        self.assertTrue(any("/sius_shots?" in url for url in urls))
        shot_requests = [request for request, _ in requests if "/sius_shots?" in request.full_url]
        shot_payload = json.loads(shot_requests[0].data)
        self.assertEqual(shot_payload[0]["raw_event_key"], "raw-event-1")


if __name__ == "__main__":
    unittest.main()
