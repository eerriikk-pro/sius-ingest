"""TCP source with bounded connection attempts and automatic reconnects."""

import socket
from collections.abc import Iterator
from dataclasses import dataclass
from threading import Event
from time import monotonic
from uuid import uuid4

from sius_ingest.models import (
    ConnectionClosed,
    ConnectionHealth,
    ConnectionOpened,
    SourceEvent,
    TcpChunk,
)
from sius_ingest.time_utils import utc_now

DEFAULT_IDLE_RECONNECT_SECONDS = 10 * 60.0
DEFAULT_HEALTH_INTERVAL_SECONDS = 5 * 60.0


@dataclass(frozen=True, slots=True)
class TcpSourceConfig:
    host: str
    port: int = 4000
    connect_timeout: float = 5.0
    reconnect_delay: float = 2.0
    receive_poll_interval: float = 1.0
    receive_size: int = 64 * 1024
    reconnect: bool = True
    idle_reconnect_seconds: float | None = DEFAULT_IDLE_RECONNECT_SECONDS
    health_interval_seconds: float | None = DEFAULT_HEALTH_INTERVAL_SECONDS
    tcp_keepalive: bool = True
    keepalive_idle_seconds: int = 60
    keepalive_interval_seconds: int = 10
    keepalive_probe_count: int = 3

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("host must not be empty")
        if not 1 <= self.port <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        if self.connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive")
        if self.reconnect_delay < 0:
            raise ValueError("reconnect_delay must not be negative")
        if self.receive_poll_interval <= 0:
            raise ValueError("receive_poll_interval must be positive")
        if self.receive_size <= 0:
            raise ValueError("receive_size must be positive")
        if self.idle_reconnect_seconds is not None and self.idle_reconnect_seconds <= 0:
            raise ValueError("idle_reconnect_seconds must be positive or None")
        if self.health_interval_seconds is not None and self.health_interval_seconds <= 0:
            raise ValueError("health_interval_seconds must be positive or None")
        if self.keepalive_idle_seconds <= 0:
            raise ValueError("keepalive_idle_seconds must be positive")
        if self.keepalive_interval_seconds <= 0:
            raise ValueError("keepalive_interval_seconds must be positive")
        if self.keepalive_probe_count <= 0:
            raise ValueError("keepalive_probe_count must be positive")


class TcpSource:
    """Yield connection lifecycle events and received TCP chunks."""

    def __init__(self, config: TcpSourceConfig) -> None:
        self._config = config

    def events(self, stop_event: Event | None = None) -> Iterator[SourceEvent]:
        stop = stop_event or Event()

        while not stop.is_set():
            connection_id = uuid4()

            try:
                with socket.create_connection(
                    (self._config.host, self._config.port),
                    timeout=self._config.connect_timeout,
                ) as client:
                    if self._config.tcp_keepalive:
                        _configure_tcp_keepalive(client, self._config)
                    client.settimeout(self._config.receive_poll_interval)
                    local_address = _socket_address(client.getsockname())
                    peer_address = _socket_address(client.getpeername())

                    yield ConnectionOpened(
                        connection_id=connection_id,
                        occurred_at=utc_now(),
                        local_address=local_address,
                        peer_address=peer_address,
                    )

                    sequence = 0
                    last_data_at = monotonic()
                    next_health_at = _next_health_at(last_data_at, self._config)
                    while not stop.is_set():
                        try:
                            data = client.recv(self._config.receive_size)
                        except TimeoutError:
                            now = monotonic()
                            idle_seconds = max(0.0, now - last_data_at)
                            if (
                                self._config.idle_reconnect_seconds is not None
                                and idle_seconds >= self._config.idle_reconnect_seconds
                            ):
                                yield ConnectionClosed(
                                    connection_id=connection_id,
                                    occurred_at=utc_now(),
                                    error=(
                                        "stale stream watchdog: no TCP data for "
                                        f"{idle_seconds:.0f} seconds"
                                    ),
                                    will_reconnect=self._config.reconnect,
                                )
                                break
                            if next_health_at is not None and now >= next_health_at:
                                yield ConnectionHealth(
                                    connection_id=connection_id,
                                    occurred_at=utc_now(),
                                    idle_seconds=idle_seconds,
                                    reconnect_after_seconds=(self._config.idle_reconnect_seconds),
                                )
                                next_health_at = _advance_health_at(
                                    next_health_at,
                                    now,
                                    self._config,
                                )
                            continue

                        if not data:
                            yield ConnectionClosed(
                                connection_id=connection_id,
                                occurred_at=utc_now(),
                                error=None,
                                will_reconnect=self._config.reconnect,
                            )
                            break

                        sequence += 1
                        last_data_at = monotonic()
                        next_health_at = _next_health_at(last_data_at, self._config)
                        yield TcpChunk(
                            connection_id=connection_id,
                            sequence=sequence,
                            received_at=utc_now(),
                            data=data,
                        )

                    if stop.is_set():
                        yield ConnectionClosed(
                            connection_id=connection_id,
                            occurred_at=utc_now(),
                            error=None,
                            will_reconnect=False,
                        )

            except OSError as exc:
                will_reconnect = self._config.reconnect and not stop.is_set()
                yield ConnectionClosed(
                    connection_id=connection_id,
                    occurred_at=utc_now(),
                    error=f"{type(exc).__name__}: {exc}",
                    will_reconnect=will_reconnect,
                )

            if not self._config.reconnect or stop.is_set():
                break

            stop.wait(self._config.reconnect_delay)


def _socket_address(value: tuple[object, ...]) -> tuple[str, int]:
    """Normalize the leading host and port fields returned by a socket."""

    return str(value[0]), int(value[1])


def _next_health_at(started_at: float, config: TcpSourceConfig) -> float | None:
    if config.health_interval_seconds is None:
        return None
    return started_at + config.health_interval_seconds


def _advance_health_at(
    previous: float,
    now: float,
    config: TcpSourceConfig,
) -> float | None:
    interval = config.health_interval_seconds
    if interval is None:
        return None
    elapsed_intervals = int(max(0.0, now - previous) // interval) + 1
    return previous + (elapsed_intervals * interval)


def _configure_tcp_keepalive(client: socket.socket, config: TcpSourceConfig) -> None:
    """Enable best-effort platform keepalive without rejecting a usable socket."""

    client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    windows_ioctl = getattr(socket, "SIO_KEEPALIVE_VALS", None)
    if windows_ioctl is not None and hasattr(client, "ioctl"):
        try:
            client.ioctl(
                windows_ioctl,
                (
                    1,
                    config.keepalive_idle_seconds * 1000,
                    config.keepalive_interval_seconds * 1000,
                ),
            )
        except OSError:
            pass
        return

    for option_name, value in (
        ("TCP_KEEPIDLE", config.keepalive_idle_seconds),
        ("TCP_KEEPALIVE", config.keepalive_idle_seconds),
        ("TCP_KEEPINTVL", config.keepalive_interval_seconds),
        ("TCP_KEEPCNT", config.keepalive_probe_count),
    ):
        option = getattr(socket, option_name, None)
        if option is None:
            continue
        try:
            client.setsockopt(socket.IPPROTO_TCP, option, value)
        except OSError:
            pass
