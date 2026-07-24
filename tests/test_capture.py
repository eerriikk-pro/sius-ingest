import json
import unittest
from base64 import b64decode
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sius_ingest.capture import CaptureWriter, create_capture_directory
from sius_ingest.models import ConnectionClosed, ConnectionOpened, FramedRecord, TcpChunk


class CaptureWriterTests(unittest.TestCase):
    def test_preserves_payload_and_metadata(self) -> None:
        started_at = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
        connection_id = uuid4()
        data = b"_SHOT;1;10.6\r\n"

        with TemporaryDirectory() as temporary:
            directory = create_capture_directory(Path(temporary), started_at)
            with CaptureWriter(
                directory,
                host="192.168.1.101",
                port=4000,
                started_at=started_at,
            ) as writer:
                writer.write_connection(
                    ConnectionOpened(
                        connection_id=connection_id,
                        occurred_at=started_at,
                        local_address=("192.168.1.100", 50000),
                        peer_address=("192.168.1.101", 4000),
                    )
                )
                writer.write_chunk(
                    TcpChunk(
                        connection_id=connection_id,
                        sequence=1,
                        received_at=started_at,
                        data=data,
                    )
                )
                writer.write_record(
                    FramedRecord(
                        connection_id=connection_id,
                        sequence=1,
                        completed_at=started_at,
                        raw=b"_SHOT;1;10.6",
                        delimiter=b"\r\n",
                        complete=True,
                    )
                )
                writer.write_connection(
                    ConnectionClosed(
                        connection_id=connection_id,
                        occurred_at=started_at,
                        error=None,
                        will_reconnect=False,
                    )
                )

            self.assertEqual((directory / "payload.bin").read_bytes(), data)

            chunk = json.loads((directory / "chunks.jsonl").read_text().strip())
            self.assertEqual(b64decode(chunk["data_base64"]), data)
            self.assertEqual(chunk["size"], len(data))

            session = json.loads((directory / "session.json").read_text())
            self.assertEqual(session["status"], "complete")
            self.assertEqual(session["counts"]["connections_opened"], 1)
            self.assertEqual(session["counts"]["chunks"], 1)
            self.assertEqual(session["counts"]["records"], 1)
            self.assertEqual(session["counts"]["bytes"], len(data))


if __name__ == "__main__":
    unittest.main()
