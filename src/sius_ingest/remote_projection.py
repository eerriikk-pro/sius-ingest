"""Durable Supabase checkpoint, lane state, and projection commits."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sius_ingest import __version__
from sius_ingest.models import LaneState, ShotKind
from sius_ingest.projection import ProjectionPage
from sius_ingest.time_utils import parse_utc
from sius_ingest.uploader import SupabaseConfig, _authentication_headers

HttpOpen = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class RemoteProjectionState:
    """The server-authoritative position and lane state for one projection."""

    last_ingest_id: int
    processed_events: int
    normalizer_version: str
    lane_states: dict[tuple[str, int], LaneState]


@dataclass(frozen=True, slots=True)
class ProjectionCommitSummary:
    """Server-confirmed result of one atomic page commit."""

    last_ingest_id: int
    processed_events: int
    committed_shots: int
    recorded_errors: int


class RemoteProjectionError(RuntimeError):
    """Supabase projection state could not be read or committed."""


class RemoteProjectionConflict(RemoteProjectionError):
    """Another worker advanced the projection checkpoint first."""


class RemoteProjectionVersionError(RemoteProjectionError):
    """Stored state belongs to incompatible projection logic."""


class SupabaseProjectionRepository:
    """Read durable projection state and atomically commit projected pages."""

    def __init__(
        self,
        *,
        config: SupabaseConfig,
        http_open: HttpOpen = urlopen,
    ) -> None:
        self._config = config
        self._http_open = http_open

    def load_state(
        self,
        *,
        projection_name: str,
        normalizer_version: str,
    ) -> RemoteProjectionState:
        state_query = urlencode(
            {
                "select": "last_ingest_id,processed_events,normalizer_version",
                "name": f"eq.{projection_name}",
                "limit": "1",
            }
        )
        rows = self._request_json(
            method="GET",
            path=f"/rest/v1/sius_projection_state?{state_query}",
        )
        if not isinstance(rows, list):
            raise RemoteProjectionError("projection state response must be a JSON array")

        if rows:
            row = _required_object(rows[0], "projection state")
            stored_version = _required_text(row, "normalizer_version")
            if stored_version != normalizer_version:
                raise RemoteProjectionVersionError(
                    f"projection {projection_name!r} uses {stored_version!r}; "
                    f"this worker uses {normalizer_version!r}"
                )
            last_ingest_id = _required_int(row, "last_ingest_id")
            processed_events = _required_int(row, "processed_events")
        else:
            stored_version = normalizer_version
            last_ingest_id = 0
            processed_events = 0

        lane_query = urlencode(
            {
                "select": (
                    "range_id,lane_number,firing_point_index,shooter_number,"
                    "session_id,phase_id,phase_kind,last_shot_number,last_shot_key,"
                    "last_annual_ticks,last_activity_at,match_ordinal,sighter_ordinal"
                ),
                "projection_name": f"eq.{projection_name}",
                "order": "range_id.asc,lane_number.asc",
            }
        )
        lane_rows = self._request_json(
            method="GET",
            path=f"/rest/v1/sius_projection_lane_state?{lane_query}",
        )
        if not isinstance(lane_rows, list):
            raise RemoteProjectionError("lane state response must be a JSON array")
        lane_states = {}
        for value in lane_rows:
            state = _decode_lane_state(_required_object(value, "lane state"))
            lane_states[(state.range_id, state.lane_number)] = state

        return RemoteProjectionState(
            last_ingest_id=last_ingest_id,
            processed_events=processed_events,
            normalizer_version=stored_version,
            lane_states=lane_states,
        )

    def existing_shot_keys(self, shot_keys: set[str]) -> set[str]:
        if not shot_keys:
            return set()
        payload = self._request_json(
            method="POST",
            path="/rest/v1/rpc/sius_existing_shot_keys",
            body={"p_shot_keys": sorted(shot_keys)},
        )
        if not isinstance(payload, list):
            raise RemoteProjectionError("existing-shot response must be a JSON array")
        existing = set()
        for value in payload:
            row = _required_object(value, "existing shot")
            existing.add(_required_text(row, "shot_key"))
        return existing

    def mark_success(
        self,
        *,
        projection_name: str,
        normalizer_version: str,
    ) -> None:
        self._request_json(
            method="POST",
            path="/rest/v1/rpc/sius_touch_projection",
            body={
                "p_projection_name": projection_name,
                "p_normalizer_version": normalizer_version,
            },
        )

    def commit_page(
        self,
        *,
        projection_name: str,
        normalizer_version: str,
        expected_last_ingest_id: int,
        next_last_ingest_id: int,
        page: ProjectionPage,
    ) -> ProjectionCommitSummary:
        payload = self._request_json(
            method="POST",
            path="/rest/v1/rpc/sius_commit_projection_batch",
            body={
                "p_projection_name": projection_name,
                "p_normalizer_version": normalizer_version,
                "p_expected_last_ingest_id": expected_last_ingest_id,
                "p_next_last_ingest_id": next_last_ingest_id,
                "p_processed_events": page.processed_events,
                "p_batch": page.payload(),
            },
        )
        row = _required_object(payload, "projection commit")
        return ProjectionCommitSummary(
            last_ingest_id=_required_int(row, "last_ingest_id"),
            processed_events=_required_int(row, "processed_events"),
            committed_shots=_required_int(row, "committed_shots"),
            recorded_errors=_required_int(row, "recorded_errors"),
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
    ) -> object:
        encoded_body = (
            json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode()
            if body is not None
            else None
        )
        headers = {
            **_authentication_headers(self._config.api_key),
            "Accept": "application/json",
            "User-Agent": f"sius-ingest/{__version__}",
        }
        if encoded_body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._config.url.rstrip('/')}{path}",
            data=encoded_body,
            method=method,
            headers=headers,
        )

        try:
            with self._http_open(request, timeout=self._config.timeout) as response:
                status = int(response.status)
                response_body = response.read()
                if status not in {200, 201}:
                    detail = response_body[:1000].decode("utf-8", errors="replace")
                    raise RemoteProjectionError(f"Supabase returned HTTP {status}: {detail}")
        except HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            message = f"Supabase returned HTTP {exc.code}: {detail}"
            if "projection checkpoint conflict" in detail:
                raise RemoteProjectionConflict(message) from exc
            if "normalizer version mismatch" in detail:
                raise RemoteProjectionVersionError(message) from exc
            raise RemoteProjectionError(message) from exc
        except URLError as exc:
            raise RemoteProjectionError(f"Supabase connection failed: {exc.reason}") from exc
        except OSError as exc:
            raise RemoteProjectionError(f"Supabase connection failed: {exc}") from exc

        try:
            return json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteProjectionError("Supabase returned invalid JSON") from exc


def _decode_lane_state(row: dict[str, object]) -> LaneState:
    return LaneState(
        range_id=_required_text(row, "range_id"),
        lane_number=_required_int(row, "lane_number"),
        firing_point_index=_required_int(row, "firing_point_index"),
        shooter_number=_optional_text(row.get("shooter_number")),
        session_id=_required_text(row, "session_id"),
        phase_id=_required_text(row, "phase_id"),
        phase_kind=ShotKind(_required_text(row, "phase_kind")),
        last_shot_number=_required_int(row, "last_shot_number"),
        last_shot_key=_required_text(row, "last_shot_key"),
        last_annual_ticks=_required_int(row, "last_annual_ticks"),
        last_activity_at=parse_utc(_required_text(row, "last_activity_at")),
        match_ordinal=_required_int(row, "match_ordinal"),
        sighter_ordinal=_required_int(row, "sighter_ordinal"),
    )


def _required_object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RemoteProjectionError(f"{name} response must be a JSON object")
    return value


def _required_text(value: dict[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise RemoteProjectionError(f"{field} must be non-empty text")
    return item


def _required_int(value: dict[str, object], field: str) -> int:
    try:
        return int(value[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteProjectionError(f"{field} must be an integer") from exc


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None
