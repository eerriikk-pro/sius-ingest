"""Record parsing and durable ingestion orchestration."""

from dataclasses import dataclass

from sius_ingest.models import FramedRecord, IngestResult
from sius_ingest.outbox import SQLiteEventStore
from sius_ingest.parser import PARSER_VERSION, ProtocolParseError, ProtocolParser
from sius_ingest.sessionizer import RelaySessionizer


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    range_id: str

    def __post_init__(self) -> None:
        if not self.range_id.strip():
            raise ValueError("range_id must not be empty")


class IngestionService:
    """Parse a framed record and atomically persist its derived state."""

    def __init__(
        self,
        *,
        store: SQLiteEventStore,
        config: IngestionConfig,
        parser: ProtocolParser | None = None,
        sessionizer: RelaySessionizer | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._parser = parser or ProtocolParser()
        self._sessionizer = sessionizer or RelaySessionizer()

    def process(self, record: FramedRecord) -> IngestResult:
        message = None
        parse_error = None

        if not record.complete:
            parse_error = f"incomplete record: {record.partial_reason or 'unknown reason'}"
        else:
            try:
                message = self._parser.parse(record.raw)
            except ProtocolParseError as exc:
                parse_error = str(exc)

        return self._store.persist_record(
            record=record,
            message=message,
            parse_error=parse_error,
            parser_version=PARSER_VERSION,
            range_id=self._config.range_id,
            sessionizer=self._sessionizer,
        )
