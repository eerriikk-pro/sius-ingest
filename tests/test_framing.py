import unittest
from datetime import UTC, datetime
from uuid import uuid4

from sius_ingest.framing import NewlineFramer
from sius_ingest.models import TcpChunk


class NewlineFramerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection_id = uuid4()
        self.received_at = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)

    def chunk(self, sequence: int, data: bytes) -> TcpChunk:
        return TcpChunk(
            connection_id=self.connection_id,
            sequence=sequence,
            received_at=self.received_at,
            data=data,
        )

    def test_reassembles_fragmented_and_batched_records(self) -> None:
        framer = NewlineFramer()

        self.assertEqual(framer.feed(self.chunk(1, b"_SH")), [])
        records = framer.feed(self.chunk(2, b"OT;one\r\n_STAT;two\npartial"))

        self.assertEqual([record.raw for record in records], [b"_SHOT;one", b"_STAT;two"])
        self.assertEqual([record.delimiter for record in records], [b"\r\n", b"\n"])
        self.assertTrue(all(record.complete for record in records))

        partial = framer.finish()
        self.assertIsNotNone(partial)
        assert partial is not None
        self.assertEqual(partial.raw, b"partial")
        self.assertEqual(partial.delimiter, b"")
        self.assertFalse(partial.complete)
        self.assertEqual(partial.partial_reason, "connection_closed")

    def test_finish_resets_connection_and_sequence(self) -> None:
        framer = NewlineFramer()
        first = framer.feed(self.chunk(1, b"one\n"))
        self.assertEqual(first[0].sequence, 1)
        self.assertIsNone(framer.finish())

        next_connection = uuid4()
        next_records = framer.feed(
            TcpChunk(
                connection_id=next_connection,
                sequence=1,
                received_at=self.received_at,
                data=b"two\n",
            )
        )
        self.assertEqual(next_records[0].sequence, 1)

    def test_limits_memory_when_no_newline_is_present(self) -> None:
        framer = NewlineFramer(max_record_size=4)

        records = framer.feed(self.chunk(1, b"abcdef"))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].raw, b"abcd")
        self.assertFalse(records[0].complete)
        self.assertEqual(records[0].partial_reason, "buffer_limit")

        partial = framer.finish()
        self.assertIsNotNone(partial)
        assert partial is not None
        self.assertEqual(partial.raw, b"ef")


if __name__ == "__main__":
    unittest.main()
