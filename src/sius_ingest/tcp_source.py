"""TCP source with bounded connection attempts and automatic reconnects."""

import socket
from collections.abc import Iterator
from dataclasses import dataclass
from threading import Event
from uuid import uuid4

from sius_ingest.models import (
    ConnectionClosed,
    ConnectionOpened,
    SourceEvent,
    TcpChunk,
)
from sius_ingest.time_utils import utc_now


@dataclass(frozen=True, slots=True)
class TcpSourceConfig:
    host: str
    port: int = 4000
    connect_timeout: float = 5.0
    reconnect_delay: float = 2.0
    receive_poll_interval: float = 1.0
    receive_size: int = 64 * 1024
    reconnect: bool = True

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
                    while not stop.is_set():
                        try:
                            data = client.recv(self._config.receive_size)
                        except TimeoutError:
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
