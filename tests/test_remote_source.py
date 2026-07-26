import json
import unittest
from base64 import b64encode
from urllib.parse import parse_qs, urlparse

from sius_ingest.remote_source import SupabaseRawEventSource
from sius_ingest.uploader import SupabaseConfig
from tests.helpers import CONNECTION_ID


class FakeResponse:
    status = 200

    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _: int = -1) -> bytes:
        return self._body


class SupabaseRawEventSourceTests(unittest.TestCase):
    def test_fetches_and_decodes_monotonic_raw_events(self) -> None:
        raw = b"_STAT;5;6;0;50;0"
        delimiter = b"\r\n"
        requests = []

        def open_request(request, *, timeout):
            requests.append((request, timeout))
            return FakeResponse(
                [
                    {
                        "ingest_id": 42,
                        "event_key": "event-42",
                        "range_id": "range-a",
                        "connection_id": str(CONNECTION_ID),
                        "record_sequence": 9,
                        "received_at": "2026-07-25T00:01:31.374Z",
                        "raw_base64": b64encode(raw).decode(),
                        "delimiter_base64": b64encode(delimiter).decode(),
                        "complete": True,
                        "partial_reason": None,
                    }
                ]
            )

        source = SupabaseRawEventSource(
            config=SupabaseConfig(
                url="https://example.supabase.co",
                api_key="sb_secret_test",
            ),
            http_open=open_request,
        )
        events = source.fetch_after(41, limit=100)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].ingest_id, 42)
        self.assertEqual(events[0].event_key, "event-42")
        self.assertEqual(events[0].record.raw, raw)
        self.assertEqual(events[0].record.delimiter, delimiter)
        query = parse_qs(urlparse(requests[0][0].full_url).query)
        self.assertEqual(query["ingest_id"], ["gt.41"])
        self.assertEqual(query["order"], ["ingest_id.asc"])
        self.assertEqual(query["limit"], ["100"])


if __name__ == "__main__":
    unittest.main()
