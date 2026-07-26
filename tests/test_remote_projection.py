import json
import unittest

from sius_ingest.projection import ProjectionPage
from sius_ingest.remote_projection import SupabaseProjectionRepository
from sius_ingest.uploader import SupabaseConfig


class FakeResponse:
    status = 200

    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _: int = -1) -> bytes:
        return self._body


EMPTY_PAGE = ProjectionPage(
    processed_events=1,
    parsed_shots=0,
    duplicate_shots=0,
    parse_errors=0,
    quarantined_shots=0,
    session_starts=(),
    phase_starts=(),
    session_activity=(),
    session_closures=(),
    phase_closures=(),
    shots=(),
    lane_states=(),
    errors=(),
)


class SupabaseProjectionRepositoryTests(unittest.TestCase):
    def test_loads_remote_checkpoint_and_lane_state(self) -> None:
        responses = iter(
            [
                [
                    {
                        "last_ingest_id": 42,
                        "processed_events": 41,
                        "normalizer_version": "projection-v2",
                    }
                ],
                [
                    {
                        "range_id": "range-a",
                        "lane_number": 6,
                        "firing_point_index": 5,
                        "shooter_number": "513",
                        "session_id": "session-1",
                        "phase_id": "phase-1",
                        "phase_kind": "match",
                        "last_shot_number": 3,
                        "last_shot_key": "shot-3",
                        "last_annual_ticks": 1003,
                        "last_activity_at": "2026-07-25T00:15:10.465Z",
                        "match_ordinal": 1,
                        "sighter_ordinal": 1,
                    }
                ],
            ]
        )

        def open_request(request, *, timeout):
            return FakeResponse(next(responses))

        repository = SupabaseProjectionRepository(
            config=SupabaseConfig(
                url="https://example.supabase.co",
                api_key="sb_secret_test",
            ),
            http_open=open_request,
        )

        state = repository.load_state(
            projection_name="default",
            normalizer_version="projection-v2",
        )

        self.assertEqual(state.last_ingest_id, 42)
        self.assertIn(("range-a", 6), state.lane_states)
        self.assertEqual(state.lane_states[("range-a", 6)].shooter_number, "513")

    def test_queries_existing_keys_and_commits_one_uniform_rpc_object(self) -> None:
        requests = []
        responses = iter(
            [
                [{"shot_key": "shot-a"}],
                {
                    "last_ingest_id": 9,
                    "processed_events": 9,
                },
                {
                    "last_ingest_id": 10,
                    "processed_events": 10,
                    "committed_shots": 0,
                    "recorded_errors": 0,
                },
            ]
        )

        def open_request(request, *, timeout):
            requests.append(request)
            return FakeResponse(next(responses))

        repository = SupabaseProjectionRepository(
            config=SupabaseConfig(
                url="https://example.supabase.co",
                api_key="sb_secret_test",
            ),
            http_open=open_request,
        )

        existing = repository.existing_shot_keys({"shot-a", "shot-b"})
        repository.mark_success(
            projection_name="default",
            normalizer_version="projection-v2",
        )
        summary = repository.commit_page(
            projection_name="default",
            normalizer_version="projection-v2",
            expected_last_ingest_id=9,
            next_last_ingest_id=10,
            page=EMPTY_PAGE,
        )

        self.assertEqual(existing, {"shot-a"})
        self.assertEqual(summary.last_ingest_id, 10)
        body = json.loads(requests[2].data)
        self.assertEqual(
            set(body),
            {
                "p_projection_name",
                "p_normalizer_version",
                "p_expected_last_ingest_id",
                "p_next_last_ingest_id",
                "p_processed_events",
                "p_batch",
            },
        )
        self.assertEqual(
            set(body["p_batch"]),
            {
                "session_starts",
                "phase_starts",
                "session_activity",
                "session_closures",
                "phase_closures",
                "shots",
                "lane_states",
                "errors",
            },
        )


if __name__ == "__main__":
    unittest.main()
