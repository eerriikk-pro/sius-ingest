import socket
import unittest
from threading import Event, Thread

from sius_ingest.models import ConnectionClosed, ConnectionHealth, ConnectionOpened, TcpChunk
from sius_ingest.tcp_source import TcpSource, TcpSourceConfig


class TcpSourceTests(unittest.TestCase):
    def test_receives_all_bytes_from_a_local_server(self) -> None:
        expected = b"_SHOT;one\r\n_STAT;two\n"

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            host, port = listener.getsockname()

            def serve() -> None:
                connection, _ = listener.accept()
                with connection:
                    connection.sendall(expected[:7])
                    connection.sendall(expected[7:])

            server = Thread(target=serve, daemon=True)
            server.start()

            source = TcpSource(
                TcpSourceConfig(
                    host=host,
                    port=port,
                    receive_poll_interval=0.05,
                    reconnect=False,
                )
            )
            events = list(source.events())
            server.join(timeout=1)

        self.assertIsInstance(events[0], ConnectionOpened)
        self.assertIsInstance(events[-1], ConnectionClosed)
        received = b"".join(event.data for event in events if isinstance(event, TcpChunk))
        self.assertEqual(received, expected)

    def test_reconnects_when_an_open_connection_stops_sending(self) -> None:
        expected = b"_SHOT;recovered\r\n"
        server_errors: list[BaseException] = []

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(2)
            listener.settimeout(2)
            host, port = listener.getsockname()

            def serve() -> None:
                try:
                    first_connection, _ = listener.accept()
                    with first_connection:
                        first_connection.settimeout(2)
                        self.assertEqual(first_connection.recv(1), b"")

                    second_connection, _ = listener.accept()
                    with second_connection:
                        second_connection.sendall(expected)
                except BaseException as exc:
                    server_errors.append(exc)

            server = Thread(target=serve, daemon=True)
            server.start()

            stop = Event()
            source = TcpSource(
                TcpSourceConfig(
                    host=host,
                    port=port,
                    receive_poll_interval=0.01,
                    reconnect_delay=0,
                    idle_reconnect_seconds=0.08,
                    health_interval_seconds=0.03,
                )
            )
            events = []
            for event in source.events(stop):
                events.append(event)
                if isinstance(event, TcpChunk):
                    stop.set()

            server.join(timeout=2)

        self.assertFalse(server.is_alive())
        self.assertEqual(server_errors, [])
        self.assertEqual(
            len([event for event in events if isinstance(event, ConnectionOpened)]),
            2,
        )
        self.assertTrue(any(isinstance(event, ConnectionHealth) for event in events))
        stale_closes = [
            event
            for event in events
            if isinstance(event, ConnectionClosed)
            and event.error
            and event.error.startswith("stale stream watchdog:")
        ]
        self.assertEqual(len(stale_closes), 1)
        self.assertTrue(stale_closes[0].will_reconnect)
        received = b"".join(event.data for event in events if isinstance(event, TcpChunk))
        self.assertEqual(received, expected)

    def test_idle_watchdog_and_health_reporting_are_disabled_by_default(self) -> None:
        config = TcpSourceConfig(host="127.0.0.1")

        self.assertIsNone(config.idle_reconnect_seconds)
        self.assertIsNone(config.health_interval_seconds)

    def test_rejects_non_positive_watchdog_interval(self) -> None:
        with self.assertRaisesRegex(ValueError, "idle_reconnect_seconds"):
            TcpSourceConfig(host="127.0.0.1", idle_reconnect_seconds=0)


if __name__ == "__main__":
    unittest.main()
