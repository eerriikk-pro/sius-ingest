"""Replay records produced by the lossless capture writer."""

import json
from base64 import b64decode
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from sius_ingest.models import FramedRecord
from sius_ingest.time_utils import parse_utc


class ReplayError(ValueError):
    """A capture file is missing, invalid, or fails integrity checks."""


class ReplaySource:
    """Yield captured framed records in their original order."""

    def __init__(self, capture_path: Path, *, verify_hashes: bool = True) -> None:
        self._records_path = (
            capture_path / "records.jsonl" if capture_path.is_dir() else capture_path
        )
        self._verify_hashes = verify_hashes

    def records(self) -> Iterator[FramedRecord]:
        try:
            file = self._records_path.open(encoding="utf-8")
        except OSError as exc:
            raise ReplayError(f"cannot open {self._records_path}: {exc}") from exc

        with file:
            for line_number, line in enumerate(file, start=1):
                try:
                    payload = json.loads(line)
                    raw = b64decode(payload["raw_base64"], validate=True)
                    delimiter = b64decode(payload["delimiter_base64"], validate=True)
                    record = FramedRecord(
                        connection_id=UUID(payload["connection_id"]),
                        sequence=int(payload["sequence"]),
                        completed_at=parse_utc(payload["completed_at"]),
                        raw=raw,
                        delimiter=delimiter,
                        complete=bool(payload["complete"]),
                        partial_reason=payload.get("partial_reason"),
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ReplayError(
                        f"invalid record at {self._records_path}:{line_number}: {exc}"
                    ) from exc

                expected_hash = payload.get("sha256")
                if self._verify_hashes and expected_hash:
                    actual_hash = sha256(raw + delimiter).hexdigest()
                    if actual_hash != expected_hash:
                        raise ReplayError(f"hash mismatch at {self._records_path}:{line_number}")

                yield record
