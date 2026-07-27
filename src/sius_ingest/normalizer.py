"""Build durable Supabase projections from immutable raw SIUS events."""

from dataclasses import dataclass
from datetime import timedelta

from sius_ingest.projection import ProjectionBuilder
from sius_ingest.remote_projection import (
    RemoteProjectionConflict,
    RemoteProjectionError,
    RemoteProjectionState,
    SupabaseProjectionRepository,
)
from sius_ingest.remote_source import RemoteSourceError, SupabaseRawEventSource

NORMALIZER_VERSION = "projection-v2"


@dataclass(frozen=True, slots=True)
class NormalizationSummary:
    """Work committed during one catch-up pass."""

    fetched_events: int
    parsed_shots: int
    duplicate_shots: int
    parse_errors: int
    quarantined_shots: int
    committed_shots: int
    recorded_errors: int
    last_ingest_id: int


class NormalizationError(RuntimeError):
    """Projection processing cannot safely advance its durable cursor."""


class SupabaseNormalizer:
    """Consume raw events in order and atomically commit deterministic projections."""

    def __init__(
        self,
        *,
        source: SupabaseRawEventSource,
        repository: SupabaseProjectionRepository,
        projection_name: str = "default",
        page_size: int = 500,
        session_timeout: timedelta = timedelta(hours=4),
        conflict_retries: int = 3,
    ) -> None:
        if not projection_name.strip():
            raise ValueError("projection_name must not be empty")
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if session_timeout <= timedelta(0):
            raise ValueError("session_timeout must be positive")
        if conflict_retries < 0:
            raise ValueError("conflict_retries must not be negative")

        self._source = source
        self._repository = repository
        self._projection_name = projection_name
        self._page_size = page_size
        self._session_timeout = session_timeout
        self._conflict_retries = conflict_retries

    def normalize_available(self) -> NormalizationSummary:
        fetched = 0
        shots = 0
        duplicates = 0
        parse_errors = 0
        quarantined = 0
        committed_shots = 0
        recorded_errors = 0
        conflict_attempts = 0

        try:
            state = self._load_state()
            while True:
                events = self._source.fetch_after(
                    state.last_ingest_id,
                    limit=self._page_size,
                )
                if not events:
                    break

                candidate_keys = {event.stable_event_key for event in events}
                existing_shot_keys = self._repository.existing_shot_keys(candidate_keys)
                page = ProjectionBuilder(
                    lane_states=state.lane_states,
                    existing_shot_keys=existing_shot_keys,
                    session_timeout=self._session_timeout,
                ).build(events)

                try:
                    commit = self._repository.commit_page(
                        projection_name=self._projection_name,
                        normalizer_version=NORMALIZER_VERSION,
                        expected_last_ingest_id=state.last_ingest_id,
                        next_last_ingest_id=events[-1].ingest_id,
                        page=page,
                    )
                except RemoteProjectionConflict:
                    conflict_attempts += 1
                    if conflict_attempts > self._conflict_retries:
                        raise
                    state = self._load_state()
                    continue

                if commit.last_ingest_id != events[-1].ingest_id:
                    raise NormalizationError(
                        "Supabase returned an unexpected projection checkpoint"
                    )

                conflict_attempts = 0
                fetched += len(events)
                shots += page.parsed_shots
                duplicates += page.duplicate_shots
                parse_errors += page.parse_errors
                quarantined += page.quarantined_shots
                committed_shots += commit.committed_shots
                recorded_errors += commit.recorded_errors
                state = self._load_state()
            self._repository.mark_success(
                projection_name=self._projection_name,
                normalizer_version=NORMALIZER_VERSION,
            )
        except (RemoteProjectionError, RemoteSourceError) as exc:
            raise NormalizationError(str(exc)) from exc

        return NormalizationSummary(
            fetched_events=fetched,
            parsed_shots=shots,
            duplicate_shots=duplicates,
            parse_errors=parse_errors,
            quarantined_shots=quarantined,
            committed_shots=committed_shots,
            recorded_errors=recorded_errors,
            last_ingest_id=state.last_ingest_id,
        )

    def _load_state(self) -> RemoteProjectionState:
        return self._repository.load_state(
            projection_name=self._projection_name,
            normalizer_version=NORMALIZER_VERSION,
        )
