"""Lossless on-disk capture files for later inspection and replay."""

import json
from base64 import b64encode
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import IO, Any
from uuid import uuid4

from sius_ingest import __version__
from sius_ingest.models import ConnectionClosed, ConnectionOpened, FramedRecord, TcpChunk
from sius_ingest.time_utils import isoformat_utc, utc_now

SCHEMA_VERSION = 1


def create_capture_directory(base_directory: Path, started_at: datetime) -> Path:
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    directory = base_directory / f"sius-{stamp}"
    if directory.exists():
        directory = base_directory / f"sius-{stamp}-{uuid4().hex[:8]}"
    directory.mkdir(parents=True)
    return directory


class CaptureWriter:
    """Write raw payload, JSONL metadata, and a session manifest."""

    def __init__(
        self,
        directory: Path,
        *,
        host: str,
        port: int,
        started_at: datetime,
    ) -> None:
        self.directory = directory
        self._host = host
        self._port = port
        self._started_at = started_at
        self._closed = False
        self._bytes_received = 0
        self._chunks_written = 0
        self._records_written = 0
        self._connections_opened = 0

        self._payload_file: IO[bytes] = (directory / "payload.bin").open("ab")
        self._chunks_file = (directory / "chunks.jsonl").open("a", encoding="utf-8", buffering=1)
        self._records_file = (directory / "records.jsonl").open("a", encoding="utf-8", buffering=1)
        self._connections_file = (directory / "connections.jsonl").open(
            "a", encoding="utf-8", buffering=1
        )
        self._write_session(status="running", ended_at=None)

    def __enter__(self) -> "CaptureWriter":
        return self

    def __exit__(self, exception_type: object, *_: object) -> None:
        self.close(status="failed" if exception_type else "complete")

    def write_connection(self, event: ConnectionOpened | ConnectionClosed) -> None:
        if isinstance(event, ConnectionOpened):
            self._connections_opened += 1
            payload: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "kind": "connection_opened",
                "connection_id": str(event.connection_id),
                "occurred_at": isoformat_utc(event.occurred_at),
                "local_address": list(event.local_address),
                "peer_address": list(event.peer_address),
            }
        else:
            payload = {
                "schema_version": SCHEMA_VERSION,
                "kind": "connection_closed",
                "connection_id": str(event.connection_id),
                "occurred_at": isoformat_utc(event.occurred_at),
                "error": event.error,
                "will_reconnect": event.will_reconnect,
            }

        self._write_jsonl(self._connections_file, payload)

    def write_chunk(self, chunk: TcpChunk) -> None:
        self._payload_file.write(chunk.data)
        self._payload_file.flush()

        self._bytes_received += len(chunk.data)
        self._chunks_written += 1
        self._write_jsonl(
            self._chunks_file,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "tcp_chunk",
                "connection_id": str(chunk.connection_id),
                "sequence": chunk.sequence,
                "received_at": isoformat_utc(chunk.received_at),
                "size": len(chunk.data),
                "sha256": sha256(chunk.data).hexdigest(),
                "data_base64": b64encode(chunk.data).decode("ascii"),
            },
        )

    def write_record(self, record: FramedRecord) -> None:
        self._records_written += 1
        reconstructed = record.raw + record.delimiter
        self._write_jsonl(
            self._records_file,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "framed_record",
                "connection_id": str(record.connection_id),
                "sequence": record.sequence,
                "completed_at": isoformat_utc(record.completed_at),
                "complete": record.complete,
                "partial_reason": record.partial_reason,
                "size": len(record.raw),
                "sha256": sha256(reconstructed).hexdigest(),
                "raw_base64": b64encode(record.raw).decode("ascii"),
                "delimiter_base64": b64encode(record.delimiter).decode("ascii"),
                "text_latin1": record.raw.decode("latin-1"),
            },
        )

    def close(self, *, status: str = "complete") -> None:
        if self._closed:
            return

        ended_at = utc_now()
        self._payload_file.close()
        self._chunks_file.close()
        self._records_file.close()
        self._connections_file.close()
        self._write_session(status=status, ended_at=ended_at)
        self._closed = True

    def _write_session(self, *, status: str, ended_at: datetime | None) -> None:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "application": "sius-ingest",
            "application_version": __version__,
            "status": status,
            "host": self._host,
            "port": self._port,
            "started_at": isoformat_utc(self._started_at),
            "ended_at": isoformat_utc(ended_at) if ended_at else None,
            "counts": {
                "connections_opened": self._connections_opened,
                "chunks": self._chunks_written,
                "records": self._records_written,
                "bytes": self._bytes_received,
            },
        }
        destination = self.directory / "session.json"
        temporary = self.directory / ".session.json.tmp"
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)

    @staticmethod
    def _write_jsonl(file: IO[str], payload: Mapping[str, object]) -> None:
        file.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
