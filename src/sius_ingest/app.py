"""Operational CLI for live ingestion, replay, status, and upload."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import timedelta
from getpass import getpass
from pathlib import Path
from threading import Event, Thread

from sius_ingest.ingest import IngestionConfig, IngestionService
from sius_ingest.models import FramedRecord, IngestResult, StoreStatus
from sius_ingest.normalizer import NormalizationError, SupabaseNormalizer
from sius_ingest.outbox import REMOTE_RAW_EVENTS, SQLiteEventStore
from sius_ingest.remote_projection import SupabaseProjectionRepository
from sius_ingest.remote_source import SupabaseRawEventSource
from sius_ingest.replay_source import ReplaySource
from sius_ingest.runner import LiveRunnerConfig, run_live_stream
from sius_ingest.tcp_source import (
    DEFAULT_HEALTH_INTERVAL_SECONDS,
    DEFAULT_IDLE_RECONNECT_SECONDS,
)
from sius_ingest.uploader import SupabaseConfig, SupabaseUploader

DEFAULT_DATABASE = Path(os.getenv("SIUS_DATABASE", "data/sius-raw.sqlite3"))
DEFAULT_RANGE_ID = os.getenv("SIUS_RANGE_ID", "default-range")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sius-ingest",
        description="Capture raw SIUSData records and build replayable Supabase projections.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser(
        "run",
        help="capture live data and upload it when Supabase is configured",
    )
    _add_live_arguments(run)
    _add_supabase_arguments(run, combined=True)
    run.set_defaults(handler=_run_combined)

    live = subparsers.add_parser("live", help="capture and ingest the live TCP stream")
    _add_live_arguments(live)
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
    _add_supabase_arguments(upload, combined=False)
    upload.add_argument("--watch", action="store_true")
    upload.set_defaults(handler=_run_upload)

    normalize = subparsers.add_parser(
        "normalize",
        help="build sessions, phases, and shots from Supabase raw events",
    )
    normalize.add_argument("--projection-name", default="default")
    normalize.add_argument("--page-size", type=int, default=500)
    normalize.add_argument(
        "--session-timeout-minutes",
        type=float,
        default=240.0,
    )
    _add_supabase_arguments(normalize, combined=False, worker=True)
    normalize.set_defaults(handler=_run_normalize)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(_effective_argv(argv))
    return int(args.handler(args))


def _effective_argv(argv: Sequence[str] | None) -> list[str]:
    """Start collection and optional upload when launched without arguments."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    return arguments or ["run"]


def _run_combined(args: argparse.Namespace) -> int:
    """Run raw capture with an optional background Supabase uploader."""

    secret_key = _resolve_secret_key(args)
    missing_settings = [
        name
        for name, value in (
            ("SUPABASE_URL", args.url),
            ("SUPABASE_SECRET_KEY", secret_key),
        )
        if not value
    ]
    if missing_settings:
        missing = ", ".join(missing_settings)
        print(
            f"Supabase upload disabled; missing {missing}. Live data will still be stored locally.",
            flush=True,
        )
        return _run_live(args)

    if args.upload_interval <= 0:
        raise SystemExit("--upload-interval must be positive")

    # Complete schema migration before the live and upload connections open
    # concurrently. SQLite WAL then allows the writer and uploader to coexist.
    with SQLiteEventStore(args.database):
        pass

    stop_event = Event()
    uploader_thread = Thread(
        target=_run_background_uploader,
        args=(args, secret_key, stop_event),
        name="sius-supabase-uploader",
        daemon=True,
    )
    print(f"Supabase upload enabled: {args.url}", flush=True)
    uploader_thread.start()
    try:
        return _run_live(args)
    finally:
        stop_event.set()
        uploader_thread.join(timeout=args.upload_timeout + 1)
        if uploader_thread.is_alive():
            print(
                "Supabase uploader is still finishing a network request; "
                "the local outbox remains durable.",
                flush=True,
            )


def _run_live(args: argparse.Namespace) -> int:
    with SQLiteEventStore(args.database) as store:
        service = IngestionService(
            store=store,
            config=IngestionConfig(
                range_id=args.range_id,
                project_locally=False,
                enqueue_raw_upload=True,
            ),
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
                idle_reconnect_seconds=_disableable_seconds(
                    args.idle_reconnect_seconds,
                    "--idle-reconnect-seconds",
                ),
                health_interval_seconds=_disableable_seconds(
                    args.health_interval_seconds,
                    "--health-interval-seconds",
                ),
            ),
            record_handler=ingest_record,
        )
        _print_status(store.status())
    return 0


def _run_replay(args: argparse.Namespace) -> int:
    processed = 0
    shot_records = 0
    parse_errors = 0

    with SQLiteEventStore(args.database) as store:
        service = IngestionService(
            store=store,
            config=IngestionConfig(
                range_id=args.range_id,
                project_locally=False,
                enqueue_raw_upload=True,
            ),
        )
        source = ReplaySource(args.capture, verify_hashes=not args.no_verify_hashes)
        for record in source.records():
            result = service.process(record)
            processed += 1
            shot_records += int(result.shot_kind is not None)
            parse_errors += int(result.parse_error is not None)
            if not args.quiet:
                summary = _format_ingest_result(result)
                if summary:
                    print(summary)

        print(
            f"Replay complete: records={processed} shot_records={shot_records} "
            f"parse_errors={parse_errors}"
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
                    "pending_raw_uploads": status.pending_raw_uploads,
                    "failed_raw_uploads": status.failed_raw_uploads,
                    "pending_projection_uploads": status.pending_projection_uploads,
                    "failed_projection_uploads": status.failed_projection_uploads,
                },
                indent=2,
            )
        )
    else:
        _print_status(status)
    return 0


def _run_upload(args: argparse.Namespace) -> int:
    if not args.url:
        raise SystemExit("SUPABASE_URL is required (or pass --url)")
    secret_key = _resolve_secret_key(args)
    if not secret_key:
        raise SystemExit(
            "A Supabase secret key is required (use --prompt-secret-key on a shared PC)"
        )
    if args.interval <= 0:
        raise SystemExit("--interval must be positive")

    stop_event = Event()
    return _upload_loop(
        database=args.database,
        url=args.url,
        secret_key=secret_key,
        batch_size=args.batch_size,
        timeout=args.timeout,
        interval=args.interval,
        watch=args.watch,
        stop_event=stop_event,
        topics=(REMOTE_RAW_EVENTS,),
    )


def _run_normalize(args: argparse.Namespace) -> int:
    if not args.url:
        raise SystemExit("SUPABASE_URL is required (or pass --url)")
    secret_key = _resolve_secret_key(args)
    if not secret_key:
        raise SystemExit("A Supabase secret key is required")
    if args.session_timeout_minutes <= 0:
        raise SystemExit("--session-timeout-minutes must be positive")
    if not 1 <= args.page_size <= 1000:
        raise SystemExit("--page-size must be between 1 and 1000")

    config = SupabaseConfig(
        url=args.url,
        api_key=secret_key,
        timeout=args.timeout,
    )
    normalizer = SupabaseNormalizer(
        source=SupabaseRawEventSource(config=config),
        repository=SupabaseProjectionRepository(config=config),
        projection_name=args.projection_name,
        page_size=args.page_size,
        session_timeout=timedelta(minutes=args.session_timeout_minutes),
    )
    print(
        f"Reading new raw events from {args.url}; projection={args.projection_name}.",
        flush=True,
    )
    try:
        summary = normalizer.normalize_available()
    except NormalizationError as exc:
        print(f"normalizer error: {exc}", flush=True)
        return 1

    print(
        f"normalized events={summary.fetched_events} "
        f"shots={summary.parsed_shots} "
        f"duplicates={summary.duplicate_shots} "
        f"parse_errors={summary.parse_errors} "
        f"quarantined={summary.quarantined_shots} "
        f"committed={summary.committed_shots} "
        f"recorded_errors={summary.recorded_errors} "
        f"cursor={summary.last_ingest_id} "
        "caught_up=true",
        flush=True,
    )
    return 0


def _run_background_uploader(
    args: argparse.Namespace,
    secret_key: str,
    stop_event: Event,
) -> None:
    try:
        _upload_loop(
            database=args.database,
            url=args.url,
            secret_key=secret_key,
            batch_size=args.upload_batch_size,
            timeout=args.upload_timeout,
            interval=args.upload_interval,
            watch=True,
            stop_event=stop_event,
            topics=(REMOTE_RAW_EVENTS,),
        )
    except Exception as exc:
        print(
            f"Supabase uploader stopped unexpectedly: {type(exc).__name__}: {exc}. "
            "Collection is continuing locally.",
            flush=True,
        )


def _upload_loop(
    *,
    database: Path,
    url: str,
    secret_key: str,
    batch_size: int,
    timeout: float,
    interval: float,
    watch: bool,
    stop_event: Event,
    topics: tuple[str, ...],
) -> int:
    with SQLiteEventStore(database) as store:
        uploader = SupabaseUploader(
            store=store,
            config=SupabaseConfig(
                url=url,
                api_key=secret_key,
                timeout=timeout,
            ),
            topics=topics,
        )
        while not stop_event.is_set():
            summary = uploader.upload_once(limit=batch_size)
            if summary.attempted:
                print(
                    f"upload attempted={summary.attempted} uploaded={summary.uploaded} "
                    f"failed={summary.failed}"
                )
            if summary.error:
                print(f"upload error: {summary.error}")
                if not watch:
                    return 1
            if not watch:
                return 0
            try:
                if stop_event.wait(interval):
                    return 0
            except KeyboardInterrupt:
                stop_event.set()
                print("\nUploader stopped.")
                return 0
    return 0


def _resolve_secret_key(args: argparse.Namespace) -> str | None:
    if args.prompt_secret_key:
        return getpass("Supabase secret key: ").strip() or None
    return args.secret_key


def _add_ingestion_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--range-id", default=DEFAULT_RANGE_ID)


def _add_live_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=os.getenv("SIUS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=_env_int("SIUS_PORT", 4000))
    parser.add_argument(
        "--capture-output",
        type=Path,
        default=Path(os.getenv("SIUS_OUTPUT", "captures")),
    )
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--reconnect-delay", type=float, default=2.0)
    parser.add_argument(
        "--idle-reconnect-seconds",
        type=float,
        default=_env_float(
            "SIUS_IDLE_RECONNECT_SECONDS",
            DEFAULT_IDLE_RECONNECT_SECONDS,
        ),
        help=(
            "reconnect an open stream after this many seconds without TCP data "
            f"(default: {DEFAULT_IDLE_RECONNECT_SECONDS:.0f}; 0 disables)"
        ),
    )
    parser.add_argument(
        "--health-interval-seconds",
        type=float,
        default=_env_float(
            "SIUS_HEALTH_INTERVAL_SECONDS",
            DEFAULT_HEALTH_INTERVAL_SECONDS,
        ),
        help=(
            "report an idle connection at this interval "
            f"(default: {DEFAULT_HEALTH_INTERVAL_SECONDS:.0f}; 0 disables)"
        ),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--verbose-records",
        action="store_true",
        help="print every raw record in addition to shot summaries",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress shot summaries")
    _add_ingestion_arguments(parser)


def _add_supabase_arguments(
    parser: argparse.ArgumentParser,
    *,
    combined: bool,
    worker: bool = False,
) -> None:
    prefix = "upload-" if combined else ""
    parser.add_argument("--url", default=os.getenv("SUPABASE_URL"))
    parser.add_argument(
        "--secret-key",
        "--service-role-key",
        dest="secret_key",
        default=(os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
        help="Supabase sb_secret key (legacy service-role JWT also supported)",
    )
    parser.add_argument(
        "--prompt-secret-key",
        action="store_true",
        help="read the secret key from a masked prompt instead of command history",
    )
    parser.add_argument(f"--{prefix}timeout", type=float, default=15.0)
    if not worker:
        parser.add_argument(f"--{prefix}batch-size", type=int, default=250)
        parser.add_argument(f"--{prefix}interval", type=float, default=5.0)


def _format_ingest_result(result: IngestResult) -> str | None:
    if result.parse_error:
        return f"parse error type={result.message_type}: {result.parse_error}"
    if result.shot_duplicate:
        return None
    if result.shot_kind is None:
        return None

    assert result.score_tenths is not None
    shooter = result.shooter_number or "anonymous"
    action = "shot" if result.shot_inserted else "captured shot"
    return (
        f"{action} lane={result.lane_number} shooter={shooter} "
        f"kind={result.shot_kind} number={result.shot_number} "
        f"score={result.score_tenths / 10:.1f}"
    )


def _print_status(status: StoreStatus) -> None:
    print(
        "database "
        f"raw_events={status.raw_events} shots={status.shots} "
        f"sessions={status.sessions} phases={status.phases} "
        f"raw_uploads_pending={status.pending_raw_uploads} "
        f"raw_uploads_failed={status.failed_raw_uploads} "
        f"projection_uploads_pending={status.pending_projection_uploads} "
        f"projection_uploads_failed={status.failed_projection_uploads}"
    )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _disableable_seconds(value: float, argument_name: str) -> float | None:
    if value < 0:
        raise SystemExit(f"{argument_name} must not be negative")
    return value or None


if __name__ == "__main__":
    raise SystemExit(main())
