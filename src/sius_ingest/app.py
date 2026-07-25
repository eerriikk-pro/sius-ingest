"""Operational CLI for live ingestion, replay, status, and upload."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from threading import Event

from sius_ingest.ingest import IngestionConfig, IngestionService
from sius_ingest.models import FramedRecord, IngestResult, SessionizerConfig, StoreStatus
from sius_ingest.outbox import SQLiteEventStore
from sius_ingest.replay_source import ReplaySource
from sius_ingest.runner import LiveRunnerConfig, run_live_stream
from sius_ingest.sessionizer import RelaySessionizer
from sius_ingest.uploader import SupabaseConfig, SupabaseUploader

DEFAULT_DATABASE = Path(os.getenv("SIUS_DATABASE", "data/sius.sqlite3"))
DEFAULT_RANGE_ID = os.getenv("SIUS_RANGE_ID", "default-range")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sius-ingest",
        description="Capture, parse, segment, persist, replay, and upload SIUSData records.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    live = subparsers.add_parser("live", help="capture and ingest the live TCP stream")
    live.add_argument("--host", default=os.getenv("SIUS_HOST", "127.0.0.1"))
    live.add_argument("--port", type=int, default=_env_int("SIUS_PORT", 4000))
    live.add_argument(
        "--capture-output",
        type=Path,
        default=Path(os.getenv("SIUS_OUTPUT", "captures")),
    )
    live.add_argument("--connect-timeout", type=float, default=5.0)
    live.add_argument("--reconnect-delay", type=float, default=2.0)
    live.add_argument("--once", action="store_true")
    live.add_argument(
        "--verbose-records",
        action="store_true",
        help="print every raw record in addition to shot summaries",
    )
    live.add_argument("--quiet", action="store_true", help="suppress shot summaries")
    _add_ingestion_arguments(live)
    live.set_defaults(handler=_run_live)

    replay = subparsers.add_parser(
        "replay",
        help="ingest a capture directory or records.jsonl file",
    )
    replay.add_argument("capture", type=Path)
    replay.add_argument("--no-verify-hashes", action="store_true")
    replay.add_argument("--quiet", action="store_true")
    _add_ingestion_arguments(replay)
    replay.set_defaults(handler=_run_replay)

    status = subparsers.add_parser("status", help="show local database counts")
    status.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    status.add_argument("--json", action="store_true", dest="as_json")
    status.set_defaults(handler=_run_status)

    upload = subparsers.add_parser(
        "upload",
        help="upload the durable outbox to Supabase",
    )
    upload.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    upload.add_argument("--url", default=os.getenv("SUPABASE_URL"))
    upload.add_argument(
        "--service-role-key",
        default=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
    )
    upload.add_argument("--batch-size", type=int, default=250)
    upload.add_argument("--timeout", type=float, default=15.0)
    upload.add_argument("--watch", action="store_true")
    upload.add_argument("--interval", type=float, default=5.0)
    upload.set_defaults(handler=_run_upload)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(_effective_argv(argv))
    return int(args.handler(args))


def _effective_argv(argv: Sequence[str] | None) -> list[str]:
    """Start live collection when launched without command-line arguments."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    return arguments or ["live"]


def _run_live(args: argparse.Namespace) -> int:
    sessionizer = RelaySessionizer(
        SessionizerConfig(session_timeout=timedelta(minutes=args.session_timeout_minutes))
    )
    with SQLiteEventStore(args.database) as store:
        service = IngestionService(
            store=store,
            config=IngestionConfig(range_id=args.range_id),
            sessionizer=sessionizer,
        )

        def ingest_record(record: FramedRecord) -> str | None:
            result = service.process(record)
            return None if args.quiet else _format_ingest_result(result)

        run_live_stream(
            LiveRunnerConfig(
                host=args.host,
                port=args.port,
                output=args.capture_output,
                connect_timeout=args.connect_timeout,
                reconnect_delay=args.reconnect_delay,
                reconnect=not args.once,
                print_records=args.verbose_records,
            ),
            record_handler=ingest_record,
        )
        _print_status(store.status())
    return 0


def _run_replay(args: argparse.Namespace) -> int:
    sessionizer = RelaySessionizer(
        SessionizerConfig(session_timeout=timedelta(minutes=args.session_timeout_minutes))
    )
    processed = 0
    shots = 0
    duplicates = 0
    parse_errors = 0

    with SQLiteEventStore(args.database) as store:
        service = IngestionService(
            store=store,
            config=IngestionConfig(range_id=args.range_id),
            sessionizer=sessionizer,
        )
        source = ReplaySource(args.capture, verify_hashes=not args.no_verify_hashes)
        for record in source.records():
            result = service.process(record)
            processed += 1
            shots += int(result.shot_inserted)
            duplicates += int(result.shot_duplicate)
            parse_errors += int(result.parse_error is not None)
            if not args.quiet:
                summary = _format_ingest_result(result)
                if summary:
                    print(summary)

        print(
            f"Replay complete: records={processed} shots={shots} "
            f"duplicate_shots={duplicates} parse_errors={parse_errors}"
        )
        _print_status(store.status())
    return 0


def _run_status(args: argparse.Namespace) -> int:
    with SQLiteEventStore(args.database) as store:
        status = store.status()
    if args.as_json:
        print(
            json.dumps(
                {
                    "raw_events": status.raw_events,
                    "shots": status.shots,
                    "sessions": status.sessions,
                    "phases": status.phases,
                    "pending_uploads": status.pending_uploads,
                    "failed_uploads": status.failed_uploads,
                },
                indent=2,
            )
        )
    else:
        _print_status(status)
    return 0


def _run_upload(args: argparse.Namespace) -> int:
    if not args.url or not args.service_role_key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required "
            "(or pass --url and --service-role-key)"
        )
    if args.interval <= 0:
        raise SystemExit("--interval must be positive")

    with SQLiteEventStore(args.database) as store:
        uploader = SupabaseUploader(
            store=store,
            config=SupabaseConfig(
                url=args.url,
                service_role_key=args.service_role_key,
                timeout=args.timeout,
            ),
        )
        while True:
            summary = uploader.upload_once(limit=args.batch_size)
            if summary.attempted:
                print(
                    f"upload attempted={summary.attempted} uploaded={summary.uploaded} "
                    f"failed={summary.failed}"
                )
            if summary.error:
                print(f"upload error: {summary.error}")
                if not args.watch:
                    return 1
            if not args.watch:
                return 0
            try:
                Event().wait(args.interval)
            except KeyboardInterrupt:
                print("\nUploader stopped.")
                return 0


def _add_ingestion_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--range-id", default=DEFAULT_RANGE_ID)
    parser.add_argument(
        "--session-timeout-minutes",
        type=float,
        default=240.0,
        help="start a new athlete lane session after this idle period",
    )


def _format_ingest_result(result: IngestResult) -> str | None:
    if result.parse_error:
        return f"parse error type={result.message_type}: {result.parse_error}"
    if result.shot_duplicate:
        return (
            f"duplicate shot ignored lane={result.lane_number} "
            f"kind={result.shot_kind} number={result.shot_number}"
        )
    if not result.shot_inserted:
        return None

    assert result.score_tenths is not None
    shooter = result.shooter_number or "anonymous"
    return (
        f"shot lane={result.lane_number} shooter={shooter} "
        f"kind={result.shot_kind} number={result.shot_number} "
        f"score={result.score_tenths / 10:.1f}"
    )


def _print_status(status: StoreStatus) -> None:
    print(
        "database "
        f"raw_events={status.raw_events} shots={status.shots} "
        f"sessions={status.sessions} phases={status.phases} "
        f"pending_uploads={status.pending_uploads} "
        f"failed_uploads={status.failed_uploads}"
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
