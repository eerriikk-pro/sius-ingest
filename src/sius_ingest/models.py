"""Typed events passed between the TCP, framing, and capture layers."""

from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias
from uuid import UUID

SocketAddress: TypeAlias = tuple[str, int]


@dataclass(frozen=True, slots=True)
class ConnectionOpened:
    """A TCP connection was established."""

    connection_id: UUID
    occurred_at: datetime
    local_address: SocketAddress
    peer_address: SocketAddress


@dataclass(frozen=True, slots=True)
class TcpChunk:
    """One byte chunk returned by ``socket.recv``."""

    connection_id: UUID
    sequence: int
    received_at: datetime
    data: bytes


@dataclass(frozen=True, slots=True)
class ConnectionClosed:
    """A connection ended or a connection attempt failed."""

    connection_id: UUID
    occurred_at: datetime
    error: str | None
    will_reconnect: bool


SourceEvent: TypeAlias = ConnectionOpened | TcpChunk | ConnectionClosed


@dataclass(frozen=True, slots=True)
class FramedRecord:
    """A tentative newline-delimited record derived from TCP chunks."""

    connection_id: UUID
    sequence: int
    completed_at: datetime
    raw: bytes
    delimiter: bytes
    complete: bool
    partial_reason: str | None = None
