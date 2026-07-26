"""Read the append-only SIUS raw-event stream from Supabase."""

import json
from base64 import b64decode
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, UUID, uuid5

from sius_ingest import __version__
from sius_ingest.models import FramedRecord
from sius_ingest.time_utils import parse_utc
from sius_ingest.uploader import SupabaseConfig, _authentication_headers

HttpOpen = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class RemoteRawEvent:
    """One immutable Supabase raw event and its local replay record."""

    ingest_id: int
    event_key: str
    range_id: str
    record: FramedRecord


class RemoteSourceError(RuntimeError):
    """Supabase raw events could not be fetched or decoded safely."""


class SupabaseRawEventSource:
    """Page through raw events using their server-assigned monotonic ID."""

    def __init__(
        self,
        *,
        config: SupabaseConfig,
        http_open: HttpOpen = urlopen,
    ) -> None:
        self._config = config
        self._http_open = http_open

    def fetch_after(
        self,
        last_ingest_id: int,
        *,
        limit: int = 500,
    ) -> list[RemoteRawEvent]:
        if last_ingest_id < 0:
            raise ValueError("last_ingest_id must not be negative")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")

        query = urlencode(
            {
                "select": (
                    "ingest_id,event_key,range_id,connection_id,record_sequence,"
                    "received_at,raw_base64,delimiter_base64,complete,partial_reason"
                ),
                "ingest_id": f"gt.{last_ingest_id}",
                "order": "ingest_id.asc",
                "limit": str(limit),
            }
        )
        endpoint = f"{self._config.url.rstrip('/')}/rest/v1/sius_raw_events?{query}"
        request = Request(
            endpoint,
            method="GET",
            headers={
                **_authentication_headers(self._config.api_key),
                "Accept": "application/json",
                "User-Agent": f"sius-ingest/{__version__}",
            },
        )

        try:
            with self._http_open(request, timeout=self._config.timeout) as response:
                status = int(response.status)
                body = response.read()
                if status != 200:
                    detail = body[:1000].decode("utf-8", errors="replace")
                    raise RemoteSourceError(f"Supabase returned HTTP {status}: {detail}")
        except HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            raise RemoteSourceError(f"Supabase returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RemoteSourceError(f"Supabase connection failed: {exc.reason}") from exc
        except OSError as exc:
            raise RemoteSourceError(f"Supabase connection failed: {exc}") from exc

        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteSourceError("Supabase returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise RemoteSourceError("Supabase raw-event response must be a JSON array")

        events = [_decode_event(item) for item in payload]
        previous = last_ingest_id
        for event in events:
            if event.ingest_id <= previous:
                raise RemoteSourceError("Supabase returned non-increasing ingest IDs")
            previous = event.ingest_id
        return events


def _decode_event(value: object) -> RemoteRawEvent:
    if not isinstance(value, dict):
        raise RemoteSourceError("Supabase raw-event row must be a JSON object")
    try:
        ingest_id = int(value["ingest_id"])
        event_key = _required_text(value, "event_key")
        range_id = _required_text(value, "range_id")
        received_at = parse_utc(_required_text(value, "received_at"))
        raw = b64decode(_required_text(value, "raw_base64"), validate=True)
        delimiter = b64decode(
            _required_text(value, "delimiter_base64"),
            validate=True,
        )
        complete = value["complete"]
        if not isinstance(complete, bool):
            raise TypeError("complete must be boolean")
        connection_id = _connection_id(value.get("connection_id"), event_key)
        record_sequence_value = value.get("record_sequence")
        record_sequence = (
            int(record_sequence_value) if record_sequence_value is not None else ingest_id
        )
        partial_reason_value = value.get("partial_reason")
        partial_reason = str(partial_reason_value) if partial_reason_value is not None else None
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteSourceError(f"Invalid Supabase raw-event row: {exc}") from exc

    return RemoteRawEvent(
        ingest_id=ingest_id,
        event_key=event_key,
        range_id=range_id,
        record=FramedRecord(
            connection_id=connection_id,
            sequence=record_sequence,
            completed_at=received_at,
            raw=raw,
            delimiter=delimiter,
            complete=complete,
            partial_reason=partial_reason,
        ),
    )


def _required_text(value: dict[str, object], field: str) -> str:
    item = value[field]
    if not isinstance(item, str) or not item:
        raise TypeError(f"{field} must be non-empty text")
    return item


def _connection_id(value: object, event_key: str) -> UUID:
    if value is None:
        return uuid5(NAMESPACE_URL, f"sius-ingest:remote:{event_key}")
    return UUID(str(value))
