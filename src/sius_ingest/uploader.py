"""Optional Supabase PostgREST uploader for the durable outbox."""

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sius_ingest import __version__
from sius_ingest.models import OutboxItem
from sius_ingest.outbox import (
    REMOTE_PHASES,
    REMOTE_RAW_EVENTS,
    REMOTE_SESSIONS,
    REMOTE_SHOTS,
    SQLiteEventStore,
)
from sius_ingest.time_utils import isoformat_utc, utc_now

TOPIC_ORDER = (REMOTE_RAW_EVENTS, REMOTE_SESSIONS, REMOTE_PHASES, REMOTE_SHOTS)
CONFLICT_COLUMNS = {
    REMOTE_RAW_EVENTS: "event_key",
    REMOTE_SESSIONS: "id",
    REMOTE_PHASES: "id",
    REMOTE_SHOTS: "shot_key",
}

HttpOpen = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class SupabaseConfig:
    url: str
    api_key: str
    timeout: float = 15.0

    def __post_init__(self) -> None:
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("Supabase URL must start with http:// or https://")
        if not self.api_key:
            raise ValueError("Supabase secret key must not be empty")
        if self.api_key.startswith("sb_publishable_"):
            raise ValueError("Supabase uploader requires a secret key, not a publishable key")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


@dataclass(frozen=True, slots=True)
class UploadSummary:
    attempted: int
    uploaded: int
    failed: int
    error: str | None


class UploadError(RuntimeError):
    """A remote batch could not be accepted."""


class SupabaseUploader:
    """Upload ordered, idempotent table batches through PostgREST."""

    def __init__(
        self,
        *,
        store: SQLiteEventStore,
        config: SupabaseConfig,
        topics: Sequence[str] = TOPIC_ORDER,
        http_open: HttpOpen = urlopen,
    ) -> None:
        requested_topics = set(topics)
        unsupported = requested_topics.difference(TOPIC_ORDER)
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(f"unsupported upload topics: {names}")
        if not requested_topics:
            raise ValueError("at least one upload topic is required")
        self._store = store
        self._config = config
        self._topics = tuple(topic for topic in TOPIC_ORDER if topic in requested_topics)
        self._http_open = http_open

    def upload_once(self, *, limit: int = 250) -> UploadSummary:
        if limit <= 0:
            raise ValueError("limit must be positive")

        items = self._store.pending_outbox(limit=limit, topics=self._topics)
        if not items:
            return UploadSummary(attempted=0, uploaded=0, failed=0, error=None)

        grouped: dict[str, list[OutboxItem]] = defaultdict(list)
        for item in items:
            grouped[item.topic].append(item)

        attempted = 0
        uploaded = 0
        for topic in self._topics:
            topic_items = grouped.pop(topic, [])
            if not topic_items:
                continue
            for compatible_items in _partition_by_payload_keys(topic_items):
                attempted += len(compatible_items)
                try:
                    self._post(topic, compatible_items)
                except UploadError as exc:
                    retry_seconds = _retry_delay(compatible_items)
                    retry_at = isoformat_utc(utc_now() + timedelta(seconds=retry_seconds))
                    self._store.mark_failed(
                        compatible_items,
                        error=str(exc),
                        retry_at=retry_at,
                    )
                    return UploadSummary(
                        attempted=attempted,
                        uploaded=uploaded,
                        failed=len(compatible_items),
                        error=str(exc),
                    )
                uploaded += self._store.mark_uploaded(compatible_items)

        if grouped:
            unknown_items = [item for values in grouped.values() for item in values]
            unknown_topics = ", ".join(sorted(grouped))
            error = f"unsupported outbox topics: {unknown_topics}"
            retry_at = isoformat_utc(utc_now() + timedelta(minutes=5))
            self._store.mark_failed(unknown_items, error=error, retry_at=retry_at)
            return UploadSummary(
                attempted=attempted + len(unknown_items),
                uploaded=uploaded,
                failed=len(unknown_items),
                error=error,
            )

        return UploadSummary(
            attempted=attempted,
            uploaded=uploaded,
            failed=0,
            error=None,
        )

    def _post(self, topic: str, items: Sequence[OutboxItem]) -> None:
        conflict_column = CONFLICT_COLUMNS[topic]
        query = urlencode({"on_conflict": conflict_column})
        endpoint = f"{self._config.url.rstrip('/')}/rest/v1/{topic}?{query}"
        body = json.dumps(
            [item.payload for item in items],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode()
        headers = {
            **_authentication_headers(self._config.api_key),
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
            "User-Agent": f"sius-ingest/{__version__}",
        }
        request = Request(endpoint, data=body, method="POST", headers=headers)

        try:
            with self._http_open(request, timeout=self._config.timeout) as response:
                status = int(response.status)
                if status not in {200, 201, 204}:
                    response_body = response.read(1000).decode("utf-8", errors="replace")
                    raise UploadError(f"Supabase returned HTTP {status}: {response_body}")
        except HTTPError as exc:
            response_body = exc.read(1000).decode("utf-8", errors="replace")
            raise UploadError(f"Supabase returned HTTP {exc.code}: {response_body}") from exc
        except URLError as exc:
            raise UploadError(f"Supabase connection failed: {exc.reason}") from exc
        except OSError as exc:
            raise UploadError(f"Supabase connection failed: {exc}") from exc


def _retry_delay(items: Sequence[OutboxItem]) -> int:
    highest_attempt = max((item.attempt_count for item in items), default=0)
    return min(300, 2 ** min(highest_attempt + 1, 8))


def _partition_by_payload_keys(items: Sequence[OutboxItem]) -> list[list[OutboxItem]]:
    """Split mixed-version rows into PostgREST-compatible bulk requests."""

    partitions: dict[tuple[str, ...], list[OutboxItem]] = {}
    for item in items:
        signature = tuple(sorted(item.payload))
        partitions.setdefault(signature, []).append(item)
    return list(partitions.values())


def _authentication_headers(api_key: str) -> dict[str, str]:
    """Build headers for current opaque keys and legacy service-role JWTs."""

    headers = {"apikey": api_key}
    if not api_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {api_key}"
    return headers
