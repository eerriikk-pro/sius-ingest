"""Deterministic identifiers shared by local capture and remote projection."""

from hashlib import sha256

from sius_ingest.models import GenericMessage, ParsedMessage, ShotMessage


def observation_key(connection_id: str, sequence: int, raw_hash: str) -> str:
    """Identify one observation on one TCP connection."""

    return hash_key(connection_id, str(sequence), raw_hash)


def shot_key(range_id: str, shot: ShotMessage, raw_hash: str) -> str:
    """Identify one physical shot across reconnects and replayed observations."""

    return hash_key(
        range_id,
        "shot",
        str(shot.lane_number),
        str(shot.annual_ticks),
        str(shot.event_sequence),
        str(shot.shot_number),
        raw_hash,
    )


def stable_event_key(
    *,
    range_id: str,
    message: ParsedMessage | None,
    message_type: str | None,
    raw_hash: str,
) -> str:
    """Identify equivalent events even when their TCP observation changes."""

    if isinstance(message, ShotMessage):
        return shot_key(range_id, message, raw_hash)
    if isinstance(message, GenericMessage) and message.event_sequence is not None:
        return hash_key(
            range_id,
            message.record_type,
            str(message.lane_number),
            str(message.event_sequence),
            str(message.annual_ticks),
            raw_hash,
        )
    return hash_key(range_id, message_type or "unknown", raw_hash)


def hash_key(*parts: str) -> str:
    """Hash an unambiguous sequence of text parts."""

    return sha256("\0".join(parts).encode()).hexdigest()
