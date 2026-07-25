import json
import unittest
from base64 import b64encode
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from sius_ingest.replay_source import ReplayError, ReplaySource
from tests.helpers import CONNECTION_ID


class ReplaySourceTests(unittest.TestCase):
    def test_replays_and_verifies_capture_record(self) -> None:
        raw = b"_PRST;5;6;0;51;0"
        delimiter = b"\r\n"
        payload = {
            "connection_id": str(CONNECTION_ID),
            "sequence": 3,
            "completed_at": "2026-07-25T00:01:31.374Z",
            "complete": True,
            "partial_reason": None,
            "raw_base64": b64encode(raw).decode(),
            "delimiter_base64": b64encode(delimiter).decode(),
            "sha256": sha256(raw + delimiter).hexdigest(),
        }

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "records.jsonl"
            path.write_text(json.dumps(payload) + "\n")

            records = list(ReplaySource(path).records())

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].raw, raw)
        self.assertEqual(records[0].delimiter, delimiter)

    def test_rejects_hash_mismatch(self) -> None:
        payload = {
            "connection_id": str(CONNECTION_ID),
            "sequence": 1,
            "completed_at": "2026-07-25T00:01:31.374Z",
            "complete": True,
            "raw_base64": b64encode(b"_STAT;5;6;0;50;0").decode(),
            "delimiter_base64": b64encode(b"\n").decode(),
            "sha256": "0" * 64,
        }

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "records.jsonl"
            path.write_text(json.dumps(payload) + "\n")
            with self.assertRaises(ReplayError):
                list(ReplaySource(path).records())


if __name__ == "__main__":
    unittest.main()
