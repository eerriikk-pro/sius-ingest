from datetime import UTC, datetime, timedelta
from uuid import UUID

from sius_ingest.models import FramedRecord

CONNECTION_ID = UUID("00000000-0000-0000-0000-000000000001")
BASE_TIME = datetime(2026, 7, 25, 0, 0, tzinfo=UTC)


def shot_line(
    *,
    shooter: str = "123",
    event_sequence: int,
    shot_flags: int,
    score_tenths: int,
    shot_number: int,
    annual_ticks: int,
    lane: int = 6,
    firing_point: int = 5,
) -> bytes:
    return (
        f"_SHOT;{firing_point};{lane};{shooter};60;{event_sequence};"
        f"17:00:{event_sequence:02d}.00;3;31;{shot_flags};{score_tenths};0;0;"
        f"{shot_number};0.00100000;-0.00200000;900;0;0;655.35;"
        f"{annual_ticks};61;450;734"
    ).encode()


def framed_record(
    raw: bytes,
    *,
    sequence: int,
    seconds: int = 0,
    connection_id: UUID = CONNECTION_ID,
) -> FramedRecord:
    return FramedRecord(
        connection_id=connection_id,
        sequence=sequence,
        completed_at=BASE_TIME + timedelta(seconds=seconds),
        raw=raw,
        delimiter=b"\r\n",
        complete=True,
    )
