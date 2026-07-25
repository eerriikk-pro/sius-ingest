-- SIUS ingestion schema for Supabase/Postgres.
--
-- The collector uses deterministic client-generated keys and PostgREST
-- upserts, so replaying a capture or reconnecting to SIUSData is idempotent.

create table if not exists public.sius_raw_events (
    event_key text primary key,
    range_id text not null,
    lane_number integer,
    event_type text,
    received_at timestamptz not null,
    raw_base64 text not null,
    delimiter_base64 text not null,
    raw_sha256 text not null,
    complete boolean not null,
    parser_version text not null,
    parsed jsonb,
    parse_error text,
    created_at timestamptz not null default now()
);

create index if not exists sius_raw_events_range_lane_received_idx
    on public.sius_raw_events (range_id, lane_number, received_at);

create table if not exists public.sius_sessions (
    id uuid primary key,
    range_id text not null,
    lane_number integer not null,
    firing_point_index integer not null,
    shooter_number text,
    started_at timestamptz not null,
    last_activity_at timestamptz not null,
    ended_at timestamptz,
    updated_at timestamptz not null
);

create index if not exists sius_sessions_range_shooter_started_idx
    on public.sius_sessions (range_id, shooter_number, started_at);

create table if not exists public.sius_phases (
    id uuid primary key,
    session_id uuid not null references public.sius_sessions (id),
    range_id text not null,
    lane_number integer not null,
    phase_kind text not null check (phase_kind in ('sighter', 'match')),
    ordinal integer not null,
    started_at timestamptz not null,
    last_activity_at timestamptz not null,
    ended_at timestamptz,
    shot_count integer not null,
    score_sum_tenths integer not null,
    updated_at timestamptz not null,
    unique (session_id, phase_kind, ordinal)
);

create table if not exists public.sius_shots (
    shot_key text primary key,
    raw_event_key text not null references public.sius_raw_events (event_key),
    session_id uuid not null references public.sius_sessions (id),
    phase_id uuid not null references public.sius_phases (id),
    range_id text not null,
    lane_number integer not null,
    firing_point_index integer not null,
    shooter_number text,
    received_at timestamptz not null,
    device_time_text text not null,
    annual_ticks bigint not null,
    event_sequence integer not null,
    phase_kind text not null check (phase_kind in ('sighter', 'match')),
    shot_number integer not null,
    score_integer integer not null,
    score_tenths integer not null,
    primary_score_raw integer not null,
    secondary_score_raw integer not null,
    shot_flags_raw integer not null,
    exercise_code_raw integer not null,
    x_native numeric not null,
    y_native numeric not null,
    parser_version text not null,
    payload jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists sius_shots_session_phase_number_idx
    on public.sius_shots (session_id, phase_id, shot_number);

create index if not exists sius_shots_range_lane_received_idx
    on public.sius_shots (range_id, lane_number, received_at);

-- The uploader is intended to use a server-side service-role key. Enabling
-- RLS without public policies keeps anon/authenticated clients out by default.
alter table public.sius_raw_events enable row level security;
alter table public.sius_sessions enable row level security;
alter table public.sius_phases enable row level security;
alter table public.sius_shots enable row level security;

revoke all on table public.sius_raw_events from anon, authenticated;
revoke all on table public.sius_sessions from anon, authenticated;
revoke all on table public.sius_phases from anon, authenticated;
revoke all on table public.sius_shots from anon, authenticated;
