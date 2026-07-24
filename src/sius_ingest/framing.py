"""Best-effort newline framing that preserves the original delimiters."""

from datetime import datetime

from sius_ingest.models import FramedRecord, TcpChunk
from sius_ingest.time_utils import utc_now


class NewlineFramer:
    """Reassemble LF or CRLF records across arbitrary TCP chunks."""

    def __init__(self, max_record_size: int = 1024 * 1024) -> None:
        if max_record_size <= 0:
            raise ValueError("max_record_size must be positive")

        self._max_record_size = max_record_size
        self._connection_id = None
        self._buffer = bytearray()
        self._record_sequence = 0

    def feed(self, chunk: TcpChunk) -> list[FramedRecord]:
        if self._connection_id is None:
            self._connection_id = chunk.connection_id
        elif self._connection_id != chunk.connection_id:
            raise ValueError("finish the current connection before feeding a new one")

        self._buffer.extend(chunk.data)
        records: list[FramedRecord] = []

        while True:
            newline_index = self._buffer.find(b"\n")
            if 0 <= newline_index <= self._max_record_size:
                raw = bytes(self._buffer[:newline_index])
                del self._buffer[: newline_index + 1]

                delimiter = b"\n"
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                    delimiter = b"\r\n"

                records.append(
                    self._make_record(
                        raw=raw,
                        delimiter=delimiter,
                        complete=True,
                        completed_at=chunk.received_at,
                    )
                )
                continue

            if len(self._buffer) <= self._max_record_size:
                break

            records.append(
                self._make_record(
                    raw=bytes(self._buffer[: self._max_record_size]),
                    delimiter=b"",
                    complete=False,
                    partial_reason="buffer_limit",
                    completed_at=chunk.received_at,
                )
            )
            del self._buffer[: self._max_record_size]

        return records

    def finish(self) -> FramedRecord | None:
        """Return a final unterminated record, then reset the framer."""

        record = None
        if self._connection_id is not None and self._buffer:
            record = self._make_record(
                raw=bytes(self._buffer),
                delimiter=b"",
                complete=False,
                partial_reason="connection_closed",
                completed_at=utc_now(),
            )

        self._connection_id = None
        self._buffer.clear()
        self._record_sequence = 0
        return record

    def _make_record(
        self,
        *,
        raw: bytes,
        delimiter: bytes,
        complete: bool,
        completed_at: datetime,
        partial_reason: str | None = None,
    ) -> FramedRecord:
        assert self._connection_id is not None
        self._record_sequence += 1
        return FramedRecord(
            connection_id=self._connection_id,
            sequence=self._record_sequence,
            completed_at=completed_at,
            raw=raw,
            delimiter=delimiter,
            complete=complete,
            partial_reason=partial_reason,
        )
