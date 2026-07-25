import unittest

from sius_ingest.models import GenericMessage, ShooterIdentityMessage, ShotKind, ShotMessage
from sius_ingest.parser import ProtocolParseError, ProtocolParser, message_to_dict
from tests.helpers import shot_line


class ProtocolParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ProtocolParser()

    def test_parses_observed_sighter_score_encoding(self) -> None:
        message = self.parser.parse(
            shot_line(
                event_sequence=20,
                shot_flags=39,
                score_tenths=96,
                shot_number=1,
                annual_ticks=1768807203,
            )
        )

        self.assertIsInstance(message, ShotMessage)
        assert isinstance(message, ShotMessage)
        self.assertEqual(message.lane_number, 6)
        self.assertEqual(message.firing_point_index, 5)
        self.assertEqual(message.shooter_number, "123")
        self.assertEqual(message.shot_kind, ShotKind.SIGHTER)
        self.assertEqual(message.score_tenths, 96)
        self.assertEqual(message.integer_score, 9)

    def test_parses_observed_match_score_encoding(self) -> None:
        message = self.parser.parse(
            shot_line(
                event_sequence=23,
                shot_flags=7,
                score_tenths=73,
                shot_number=1,
                annual_ticks=1768809600,
            )
        )

        assert isinstance(message, ShotMessage)
        self.assertEqual(message.shot_kind, ShotKind.MATCH)
        self.assertEqual(message.score_tenths, 73)

    def test_normalizes_separate_integer_and_decimal_scores(self) -> None:
        raw = (
            b"_SHOT;8;9;544;60;252;16:15:43.99;3;1;39;8;88;0;1;"
            b"0.01460385;-0.00878411;900;0;0;655.35;1764845224;60;450;736"
        )

        message = self.parser.parse(raw)

        assert isinstance(message, ShotMessage)
        self.assertEqual(message.integer_score, 8)
        self.assertEqual(message.score_tenths, 88)

    def test_parses_shooter_identity(self) -> None:
        message = self.parser.parse(b"_SHID;5;6;123;1;123")

        self.assertIsInstance(message, ShooterIdentityMessage)
        assert isinstance(message, ShooterIdentityMessage)
        self.assertEqual(message.shooter_number, "123")
        self.assertEqual(message.external_number, "123")

    def test_parses_timed_unknown_message_generically(self) -> None:
        message = self.parser.parse(b"_SUBT;5;6;123;60;21;17:16:02.52;7;0;0;0;1768807647")

        self.assertIsInstance(message, GenericMessage)
        assert isinstance(message, GenericMessage)
        self.assertEqual(message.event_sequence, 21)
        self.assertEqual(message.annual_ticks, 1768807647)

    def test_json_payload_uses_strings_for_decimals(self) -> None:
        message = self.parser.parse(
            shot_line(
                event_sequence=1,
                shot_flags=7,
                score_tenths=94,
                shot_number=1,
                annual_ticks=100,
            )
        )

        payload = message_to_dict(message)

        self.assertEqual(payload["x_native"], "0.00100000")

    def test_rejects_malformed_shot(self) -> None:
        with self.assertRaises(ProtocolParseError):
            self.parser.parse(b"_SHOT;5;6")


if __name__ == "__main__":
    unittest.main()
