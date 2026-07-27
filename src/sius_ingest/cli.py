"""Command-line interface for lossless SIUSData TCP capture."""

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from sius_ingest.runner import LiveRunnerConfig, run_live_stream
from sius_ingest.tcp_source import (
    DEFAULT_HEALTH_INTERVAL_SECONDS,
    DEFAULT_IDLE_RECONNECT_SECONDS,
)


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
    run_live_stream(
        LiveRunnerConfig(
            host=args.host,
            port=args.port,
            output=args.output,
            connect_timeout=args.connect_timeout,
            reconnect_delay=args.reconnect_delay,
            reconnect=not args.once,
            print_records=not args.quiet,
            idle_reconnect_seconds=_disableable_seconds(
                args.idle_reconnect_seconds,
                "--idle-reconnect-seconds",
            ),
            health_interval_seconds=_disableable_seconds(
                args.health_interval_seconds,
                "--health-interval-seconds",
            ),
        )
    )
    return 0


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
