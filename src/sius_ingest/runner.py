"""Shared live TCP runner used by capture-only and ingestion commands."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from uuid import UUID

from sius_ingest.capture import CaptureWriter, create_capture_directory
from sius_ingest.framing import NewlineFramer
from sius_ingest.models import (
    ConnectionClosed,
    ConnectionHealth,
    ConnectionOpened,
    FramedRecord,
    TcpChunk,
)
from sius_ingest.tcp_source import (
    DEFAULT_HEALTH_INTERVAL_SECONDS,
    DEFAULT_IDLE_RECONNECT_SECONDS,
    TcpSource,
    TcpSourceConfig,
)
from sius_ingest.time_utils import isoformat_utc, utc_now

RecordHandler = Callable[[FramedRecord], str | None]


@dataclass(frozen=True, slots=True)
class LiveRunnerConfig:
    host: str
    port: int
    output: Path
    connect_timeout: float = 5.0
    reconnect_delay: float = 2.0
    reconnect: bool = True
    print_records: bool = True
    idle_reconnect_seconds: float | None = DEFAULT_IDLE_RECONNECT_SECONDS
    health_interval_seconds: float | None = DEFAULT_HEALTH_INTERVAL_SECONDS


def run_live_stream(
    config: LiveRunnerConfig,
    *,
    record_handler: RecordHandler | None = None,
) -> Path:
    """Capture a live stream and optionally pass each record to an ingester."""

    started_at = utc_now()
    capture_directory = create_capture_directory(config.output, started_at)
    stop_event = Event()
    source = TcpSource(
        TcpSourceConfig(
            host=config.host,
            port=config.port,
            connect_timeout=config.connect_timeout,
            reconnect_delay=config.reconnect_delay,
            reconnect=config.reconnect,
            idle_reconnect_seconds=config.idle_reconnect_seconds,
            health_interval_seconds=config.health_interval_seconds,
        )
    )
    framer = NewlineFramer()
    active_connection: UUID | None = None

    print(f"Capture directory: {capture_directory.resolve()}", flush=True)
    print(f"Connecting to {config.host}:{config.port}; press Control-C to stop.", flush=True)

    events = source.events(stop_event)
    with CaptureWriter(
        capture_directory,
        host=config.host,
        port=config.port,
        started_at=started_at,
    ) as writer:
        try:
            for event in events:
                if isinstance(event, ConnectionOpened):
                    active_connection = event.connection_id
                    writer.write_connection(event)
                    print(
                        f"[{isoformat_utc(event.occurred_at)}] connected id={event.connection_id}",
                        flush=True,
                    )
                elif isinstance(event, TcpChunk):
                    writer.write_chunk(event)
                    for record in framer.feed(event):
                        _handle_record(
                            writer=writer,
                            record=record,
                            print_record=config.print_records,
                            record_handler=record_handler,
                        )
                elif isinstance(event, ConnectionHealth):
                    reconnect_detail = (
                        "disabled"
                        if event.reconnect_after_seconds is None
                        else f"{event.reconnect_after_seconds:.0f}s"
                    )
                    print(
                        f"[{isoformat_utc(event.occurred_at)}] connection open but idle "
                        f"id={event.connection_id} idle={event.idle_seconds:.0f}s "
                        f"watchdog={reconnect_detail}",
                        flush=True,
                    )
                elif isinstance(event, ConnectionClosed):
                    partial = framer.finish()
                    if partial:
                        _handle_record(
                            writer=writer,
                            record=partial,
                            print_record=config.print_records,
                            record_handler=record_handler,
                        )
                    active_connection = None
                    writer.write_connection(event)
                    detail = event.error or "peer closed the connection"
                    retry = " reconnecting" if event.will_reconnect else ""
                    print(
                        f"[{isoformat_utc(event.occurred_at)}] disconnected: {detail}.{retry}",
                        flush=True,
                    )
        except KeyboardInterrupt:
            stop_event.set()
            print("\nStopping capture...", flush=True)
        finally:
            events.close()
            if active_connection is not None:
                partial = framer.finish()
                if partial:
                    _handle_record(
                        writer=writer,
                        record=partial,
                        print_record=config.print_records,
                        record_handler=record_handler,
                    )

    print(f"Capture complete: {capture_directory.resolve()}", flush=True)
    return capture_directory


def _handle_record(
    *,
    writer: CaptureWriter,
    record: FramedRecord,
    print_record: bool,
    record_handler: RecordHandler | None,
) -> None:
    writer.write_record(record)
    if print_record:
        text = record.raw.decode("latin-1")
        suffix = "" if record.complete else f" [partial: {record.partial_reason}]"
        print(
            f"[{isoformat_utc(record.completed_at)}] record {record.sequence}: "
            f"{json.dumps(text, ensure_ascii=True)}{suffix}",
            flush=True,
        )
    if record_handler:
        summary = record_handler(record)
        if summary:
            print(f"[{isoformat_utc(record.completed_at)}] {summary}", flush=True)
