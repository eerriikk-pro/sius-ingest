import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError

from sius_ingest.ingest import IngestionConfig, IngestionService
from sius_ingest.outbox import REMOTE_RAW_EVENTS, SQLiteEventStore
from sius_ingest.uploader import (
    SupabaseConfig,
    SupabaseUploader,
    _authentication_headers,
)
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
    def test_raw_only_uploader_leaves_projection_jobs_untouched(self) -> None:
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
                        api_key="sb_secret_test",
                    ),
                    topics=(REMOTE_RAW_EVENTS,),
                    http_open=open_request,
                )

                summary = uploader.upload_once()
                status = store.status()

        self.assertEqual(summary.uploaded, 1)
        self.assertEqual(len(requests), 1)
        self.assertIn("/sius_raw_events?", requests[0][0].full_url)
        self.assertEqual(status.pending_raw_uploads, 0)
        self.assertEqual(status.pending_projection_uploads, 3)

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
                        api_key="sb_secret_test",
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
        headers = {key.lower(): value for key, value in requests[0][0].header_items()}
        self.assertEqual(headers["apikey"], "sb_secret_test")
        self.assertNotIn("authorization", headers)
        raw_payload = json.loads(requests[0][0].data)[0]
        self.assertEqual(raw_payload["connection_id"], "00000000-0000-0000-0000-000000000001")
        self.assertEqual(raw_payload["record_sequence"], 1)
        self.assertEqual(raw_payload["firing_point_index"], 5)
        self.assertEqual(raw_payload["lane_number"], 6)
        self.assertEqual(raw_payload["shooter_number"], "123")
        self.assertEqual(raw_payload["event_sequence"], 1)
        self.assertEqual(raw_payload["device_time_text"], "17:00:01.00")
        self.assertEqual(raw_payload["annual_ticks"], 1001)
        self.assertEqual(len(raw_payload["stable_event_key"]), 64)
        self.assertEqual(raw_payload["fields"][0], "_SHOT")
        self.assertEqual(len(raw_payload["fields"]), 24)
        self.assertTrue(raw_payload["raw_text"].startswith("_SHOT;5;6;123;"))
        self.assertGreater(raw_payload["raw_size_bytes"], 0)
        shot_payload = json.loads(requests[3][0].data)
        self.assertEqual(shot_payload[0]["score_tenths"], 94)

    def test_partitions_mixed_schema_versions_into_compatible_batches(self) -> None:
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
                service.process(framed_record(b"_STAT;5;6;0;50;0", sequence=1))
                service.process(framed_record(b"_PRST;5;6;0;51;0", sequence=2))

                with sqlite3.connect(database) as connection:
                    row = connection.execute(
                        """
                        SELECT id, payload_json
                        FROM outbox
                        WHERE topic = 'sius_raw_events'
                        ORDER BY id
                        LIMIT 1
                        """
                    ).fetchone()
                    assert row is not None
                    legacy_payload = json.loads(row[1])
                    legacy_payload.pop("connection_id")
                    legacy_payload.pop("fields")
                    connection.execute(
                        "UPDATE outbox SET payload_json = ? WHERE id = ?",
                        (json.dumps(legacy_payload), row[0]),
                    )

                uploader = SupabaseUploader(
                    store=store,
                    config=SupabaseConfig(
                        url="https://example.supabase.co",
                        api_key="sb_secret_test",
                    ),
                    http_open=open_request,
                )

                summary = uploader.upload_once()
                status = store.status()

        self.assertEqual(summary.uploaded, 2)
        self.assertEqual(status.pending_uploads, 0)
        self.assertEqual(len(requests), 2)
        for request, _ in requests:
            self.assertIn("/sius_raw_events?", request.full_url)
            payload = json.loads(request.data)
            self.assertEqual(len(payload), 1)

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
                        api_key="sb_secret_test",
                    ),
                    http_open=fail_request,
                )

                summary = uploader.upload_once()
                status = store.status()

        self.assertEqual(summary.failed, 1)
        self.assertEqual(status.failed_uploads, 1)
        self.assertNotIn("sb_secret_test", summary.error or "")

    def test_legacy_service_role_jwt_is_sent_as_bearer_token(self) -> None:
        self.assertEqual(
            _authentication_headers("eyJlegacy-service-role"),
            {
                "apikey": "eyJlegacy-service-role",
                "Authorization": "Bearer eyJlegacy-service-role",
            },
        )

    def test_publishable_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a publishable key"):
            SupabaseConfig(
                url="https://example.supabase.co",
                api_key="sb_publishable_test",
            )


if __name__ == "__main__":
    unittest.main()
