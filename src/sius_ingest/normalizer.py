"""Build replayable Supabase projections from immutable raw SIUS events."""

from dataclasses import dataclass
from datetime import timedelta

from sius_ingest.ingest import IngestionConfig, IngestionService
from sius_ingest.models import SessionizerConfig
from sius_ingest.outbox import (
    REMOTE_PHASES,
    REMOTE_SESSIONS,
    REMOTE_SHOTS,
    SQLiteEventStore,
)
from sius_ingest.remote_source import SupabaseRawEventSource
from sius_ingest.sessionizer import RelaySessionizer
from sius_ingest.uploader import SupabaseUploader

NORMALIZER_VERSION = "projection-v1"
PROJECTION_TOPICS = (REMOTE_SESSIONS, REMOTE_PHASES, REMOTE_SHOTS)


@dataclass(frozen=True, slots=True)
class NormalizationSummary:
    """Work completed during one catch-up pass."""

    fetched_events: int
    parsed_shots: int
    duplicate_shots: int
    parse_errors: int
    uploaded_rows: int
    last_ingest_id: int


class NormalizationError(RuntimeError):
    """Projection processing cannot safely advance its durable cursor."""


class SupabaseNormalizer:
    """Consume raw events in order and upload their deterministic projections."""

    def __init__(
        self,
        *,
        store: SQLiteEventStore,
        source: SupabaseRawEventSource,
        uploader: SupabaseUploader,
        projection_name: str = "default",
        page_size: int = 500,
        upload_batch_size: int = 250,
        session_timeout: timedelta = timedelta(hours=4),
    ) -> None:
        if not projection_name.strip():
            raise ValueError("projection_name must not be empty")
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if upload_batch_size <= 0:
            raise ValueError("upload_batch_size must be positive")
        if session_timeout <= timedelta(0):
            raise ValueError("session_timeout must be positive")

        self._store = store
        self._source = source
        self._uploader = uploader
        self._projection_name = projection_name
        self._page_size = page_size
        self._upload_batch_size = upload_batch_size
        self._session_timeout = session_timeout
        self._services: dict[str, IngestionService] = {}

    def normalize_available(self) -> NormalizationSummary:
        cursor = self._store.projection_cursor(self._projection_name)
        if cursor and cursor.normalizer_version != NORMALIZER_VERSION:
            raise NormalizationError("normalizer version changed; use a fresh normalizer database")

        last_ingest_id = cursor.last_ingest_id if cursor else 0
        processed_events = cursor.processed_events if cursor else 0
        uploaded = self._flush_projection_outbox()
        fetched = 0
        shots = 0
        duplicates = 0
        parse_errors = 0

        while True:
            events = self._source.fetch_after(
                last_ingest_id,
                limit=self._page_size,
            )
            if not events:
                break

            for event in events:
                service = self._service_for_range(event.range_id)
                result = service.process(
                    event.record,
                    source_event_key=event.event_key,
                )
                fetched += 1
                shots += int(result.shot_inserted)
                duplicates += int(result.shot_duplicate)
                parse_errors += int(result.parse_error is not None)

            uploaded += self._flush_projection_outbox()
            last_ingest_id = events[-1].ingest_id
            processed_events += len(events)
            self._store.save_projection_cursor(
                name=self._projection_name,
                last_ingest_id=last_ingest_id,
                processed_events=processed_events,
                normalizer_version=NORMALIZER_VERSION,
            )

            if len(events) < self._page_size:
                break

        return NormalizationSummary(
            fetched_events=fetched,
            parsed_shots=shots,
            duplicate_shots=duplicates,
            parse_errors=parse_errors,
            uploaded_rows=uploaded,
            last_ingest_id=last_ingest_id,
        )

    def _service_for_range(self, range_id: str) -> IngestionService:
        service = self._services.get(range_id)
        if service is None:
            service = IngestionService(
                store=self._store,
                config=IngestionConfig(
                    range_id=range_id,
                    project_locally=True,
                    enqueue_raw_upload=False,
                ),
                sessionizer=RelaySessionizer(
                    SessionizerConfig(session_timeout=self._session_timeout)
                ),
            )
            self._services[range_id] = service
        return service

    def _flush_projection_outbox(self) -> int:
        uploaded = 0
        while True:
            pending = self._store.pending_upload_count(PROJECTION_TOPICS)
            if pending == 0:
                return uploaded

            summary = self._uploader.upload_once(limit=self._upload_batch_size)
            uploaded += summary.uploaded
            if summary.error:
                raise NormalizationError(summary.error)
            if summary.attempted == 0:
                raise NormalizationError(
                    f"{pending} projection uploads are waiting for their retry time"
                )
