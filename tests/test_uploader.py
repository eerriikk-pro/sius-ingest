import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError

from sius_ingest.ingest import IngestionConfig, IngestionService
from sius_ingest.outbox import SQLiteEventStore
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


class SupabaseUploaderTests(unittest.TestCase):
    def test_uploads_dependency_order_and_marks_outbox_complete(self) -> None:
        requests = []

        def open_request(request, *, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "sius.sqlite3"
            with SQLiteEventStore(database) as store:
                service = IngestionService(
                    store=store,
                    config=IngestionConfig(range_id="range-a"),
                )
                service.process(
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
                uploader = SupabaseUploader(
                    store=store,
                    config=SupabaseConfig(
                        url="https://example.supabase.co",
                        service_role_key="test-secret",
                    ),
                    http_open=open_request,
                )

                summary = uploader.upload_once()
                status = store.status()

        self.assertEqual(summary.uploaded, 4)
        self.assertEqual(status.pending_uploads, 0)
        urls = [request.full_url for request, _ in requests]
        self.assertIn("/sius_raw_events?", urls[0])
        self.assertIn("/sius_sessions?", urls[1])
        self.assertIn("/sius_phases?", urls[2])
        self.assertIn("/sius_shots?", urls[3])
        shot_payload = json.loads(requests[3][0].data)
        self.assertEqual(shot_payload[0]["score_tenths"], 94)

    def test_failed_upload_remains_pending_with_error(self) -> None:
        def fail_request(request, *, timeout):
            raise URLError("offline")

        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "sius.sqlite3"
            with SQLiteEventStore(database) as store:
                service = IngestionService(
                    store=store,
                    config=IngestionConfig(range_id="range-a"),
                )
                service.process(
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
                uploader = SupabaseUploader(
                    store=store,
                    config=SupabaseConfig(
                        url="https://example.supabase.co",
                        service_role_key="test-secret",
                    ),
                    http_open=fail_request,
                )

                summary = uploader.upload_once()
                status = store.status()

        self.assertEqual(summary.failed, 1)
        self.assertEqual(status.failed_uploads, 1)
        self.assertNotIn("test-secret", summary.error or "")


if __name__ == "__main__":
    unittest.main()
