"""Command-line interface for lossless SIUSData TCP capture."""

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from threading import Event

from sius_ingest.capture import CaptureWriter, create_capture_directory
from sius_ingest.framing import NewlineFramer
from sius_ingest.models import ConnectionClosed, ConnectionOpened, FramedRecord, TcpChunk
from sius_ingest.tcp_source import TcpSource, TcpSourceConfig
from sius_ingest.time_utils import isoformat_utc, utc_now


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sius-capture",
        description="Capture the SIUSData TCP stream without assuming its schema.",
    )
    parser.add_argument("--host", default=os.getenv("SIUS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=_env_int("SIUS_PORT", 4000))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.getenv("SIUS_OUTPUT", "captures")),
        help="parent directory for timestamped captures (default: captures)",
    )
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--reconnect-delay", type=float, default=2.0)
    parser.add_argument(
        "--once",
        action="store_true",
        help="stop after the first connection ends or attempt fails",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="do not print reconstructed records",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started_at = utc_now()
    capture_directory = create_capture_directory(args.output, started_at)
    stop_event = Event()
    source = TcpSource(
        TcpSourceConfig(
            host=args.host,
            port=args.port,
            connect_timeout=args.connect_timeout,
            reconnect_delay=args.reconnect_delay,
            reconnect=not args.once,
        )
    )
    framer = NewlineFramer()
    active_connection = None

    print(f"Capture directory: {capture_directory.resolve()}", flush=True)
    print(f"Connecting to {args.host}:{args.port}; press Control-C to stop.", flush=True)

    events = source.events(stop_event)
    with CaptureWriter(
        capture_directory,
        host=args.host,
        port=args.port,
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
                        _handle_record(writer, record, quiet=args.quiet)
                elif isinstance(event, ConnectionClosed):
                    partial = framer.finish()
                    if partial:
                        _handle_record(writer, partial, quiet=args.quiet)
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
                    _handle_record(writer, partial, quiet=args.quiet)

    print(f"Capture complete: {capture_directory.resolve()}", flush=True)
    return 0


def _handle_record(writer: CaptureWriter, record: FramedRecord, *, quiet: bool) -> None:
    writer.write_record(record)
    if quiet:
        return

    text = record.raw.decode("latin-1")
    suffix = "" if record.complete else f" [partial: {record.partial_reason}]"
    print(
        f"[{isoformat_utc(record.completed_at)}] record {record.sequence}: "
        f"{json.dumps(text, ensure_ascii=True)}{suffix}",
        flush=True,
    )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


if __name__ == "__main__":
    raise SystemExit(main())
