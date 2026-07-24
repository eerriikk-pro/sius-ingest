import socket
import unittest
from threading import Thread

from sius_ingest.models import ConnectionClosed, ConnectionOpened, TcpChunk
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


if __name__ == "__main__":
    unittest.main()
