\set ON_ERROR_STOP on

truncate table
    public.sius_projection_errors,
    public.sius_projection_lane_state,
    public.sius_shots,
    public.sius_phases,
    public.sius_sessions,
    public.sius_projection_state,
    public.sius_raw_events
restart identity cascade;

insert into public.sius_raw_events (
    event_key,
    stable_event_key,
    range_id,
    event_type,
    received_at,
    raw_base64,
    delimiter_base64,
    raw_sha256,
    complete,
    parser_version
) values
    (
        'raw-1',
        'shot-1',
        'range-a',
        '_SHOT',
        '2026-07-25T00:00:01Z',
        '',
        '',
        repeat('1', 64),
        true,
        'observed-v1'
    ),
    (
        'raw-2',
        'status-2',
        'range-a',
        '_STAT',
        '2026-07-25T00:00:02Z',
        '',
        '',
        repeat('2', 64),
        true,
        'observed-v1'
    ),
    (
        'raw-3',
        'shot-3',
        'range-a',
        '_SHOT',
        '2026-07-25T00:00:03Z',
        '',
        '',
        repeat('3', 64),
        true,
        'observed-v1'
    );

set role service_role;

select public.sius_touch_projection('empty', 'projection-v2');

do $$
declare
    state_row public.sius_projection_state%rowtype;
begin
    select * into strict state_row
    from public.sius_projection_state
    where name = 'empty';
    assert state_row.last_ingest_id = 0, 'empty projection cursor was not created';
    assert state_row.last_success_at is not null, 'empty success was not recorded';
end;
$$;

select public.sius_commit_projection_batch(
    'default',
    'projection-v2',
    0,
    1,
    1,
    $json$
    {
      "session_starts": [{
        "id": "00000000-0000-0000-0000-000000000101",
        "range_id": "range-a",
        "lane_number": 6,
        "firing_point_index": 5,
        "shooter_number": "513",
        "started_at": "2026-07-25T00:00:01Z",
        "last_activity_at": "2026-07-25T00:00:01Z"
      }],
      "phase_starts": [{
        "id": "00000000-0000-0000-0000-000000000201",
        "session_id": "00000000-0000-0000-0000-000000000101",
        "range_id": "range-a",
        "lane_number": 6,
        "phase_kind": "match",
        "ordinal": 1,
        "started_at": "2026-07-25T00:00:01Z",
        "last_activity_at": "2026-07-25T00:00:01Z"
      }],
      "session_activity": [{
        "id": "00000000-0000-0000-0000-000000000101",
        "firing_point_index": 5,
        "last_activity_at": "2026-07-25T00:00:01Z"
      }],
      "session_closures": [],
      "phase_closures": [],
      "shots": [{
        "shot_key": "shot-1",
        "raw_event_key": "raw-1",
        "session_id": "00000000-0000-0000-0000-000000000101",
        "phase_id": "00000000-0000-0000-0000-000000000201",
        "range_id": "range-a",
        "lane_number": 6,
        "firing_point_index": 5,
        "shooter_number": "513",
        "received_at": "2026-07-25T00:00:01Z",
        "device_time_text": "17:00:01.00",
        "annual_ticks": 1001,
        "event_sequence": 1,
        "phase_kind": "match",
        "shot_number": 1,
        "score_integer": 9,
        "score_tenths": 94,
        "primary_score_raw": 94,
        "secondary_score_raw": 0,
        "shot_flags_raw": 7,
        "exercise_code_raw": 31,
        "x_native": "0.001",
        "y_native": "-0.002",
        "parser_version": "observed-v1",
        "payload": {}
      }],
      "lane_states": [{
        "range_id": "range-a",
        "lane_number": 6,
        "firing_point_index": 5,
        "shooter_number": "513",
        "session_id": "00000000-0000-0000-0000-000000000101",
        "phase_id": "00000000-0000-0000-0000-000000000201",
        "phase_kind": "match",
        "last_shot_number": 1,
        "last_shot_key": "shot-1",
        "last_annual_ticks": 1001,
        "last_activity_at": "2026-07-25T00:00:01Z",
        "match_ordinal": 1,
        "sighter_ordinal": 0
      }],
      "errors": []
    }
    $json$::jsonb
);

do $$
declare
    phase_row public.sius_phases%rowtype;
    state_row public.sius_projection_state%rowtype;
begin
    select * into strict phase_row
    from public.sius_phases
    where id = '00000000-0000-0000-0000-000000000201';
    assert phase_row.shot_count = 1, 'phase shot count was not recomputed';
    assert phase_row.score_sum_tenths = 94, 'phase score was not recomputed';

    select * into strict state_row
    from public.sius_projection_state
    where name = 'default';
    assert state_row.last_ingest_id = 1, 'checkpoint was not advanced';
    assert state_row.processed_events = 1, 'processed count was not advanced';
end;
$$;

do $$
begin
    perform public.sius_commit_projection_batch(
        'default',
        'projection-v2',
        0,
        1,
        1,
        '{"session_starts":[],"phase_starts":[],"session_activity":[],'
        '"session_closures":[],"phase_closures":[],"shots":[],'
        '"lane_states":[],"errors":[]}'::jsonb
    );
    raise exception 'expected checkpoint conflict';
exception
    when others then
        if position('projection checkpoint conflict' in sqlerrm) = 0 then
            raise;
        end if;
end;
$$;

select public.sius_commit_projection_batch(
    'default',
    'projection-v2',
    1,
    2,
    1,
    '{"session_starts":[],"phase_starts":[],"session_activity":[],'
    '"session_closures":[],"phase_closures":[],"shots":[],'
    '"lane_states":[],"errors":[]}'::jsonb
);

do $$
begin
    perform public.sius_commit_projection_batch(
        'default',
        'projection-v2',
        2,
        3,
        1,
        $json$
        {
          "session_starts": [],
          "phase_starts": [],
          "session_activity": [],
          "session_closures": [],
          "phase_closures": [],
          "shots": [{
            "shot_key": "shot-3",
            "raw_event_key": "raw-3",
            "session_id": "00000000-0000-0000-0000-000000000999",
            "phase_id": "00000000-0000-0000-0000-000000000999",
            "range_id": "range-a",
            "lane_number": 6,
            "firing_point_index": 5,
            "shooter_number": "513",
            "received_at": "2026-07-25T00:00:03Z",
            "device_time_text": "17:00:03.00",
            "annual_ticks": 1003,
            "event_sequence": 3,
            "phase_kind": "match",
            "shot_number": 2,
            "score_integer": 9,
            "score_tenths": 95,
            "primary_score_raw": 95,
            "secondary_score_raw": 0,
            "shot_flags_raw": 7,
            "exercise_code_raw": 31,
            "x_native": "0.001",
            "y_native": "-0.002",
            "parser_version": "observed-v1",
            "payload": {}
          }],
          "lane_states": [],
          "errors": []
        }
        $json$::jsonb
    );
    raise exception 'expected foreign-key rollback';
exception
    when foreign_key_violation then
        null;
end;
$$;

do $$
declare
    state_row public.sius_projection_state%rowtype;
begin
    select * into strict state_row
    from public.sius_projection_state
    where name = 'default';
    assert state_row.last_ingest_id = 2, 'failed page advanced checkpoint';
    assert not exists (
        select 1 from public.sius_shots where shot_key = 'shot-3'
    ), 'failed page inserted a shot';
end;
$$;

reset role;
