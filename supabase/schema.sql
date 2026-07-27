-- SIUS ingestion schema for Supabase/Postgres.
--
-- The collector uses deterministic client-generated keys and PostgREST
-- upserts, so replaying a capture or reconnecting to SIUSData is idempotent.

create table if not exists public.sius_raw_events (
    event_key text primary key,
    ingest_id bigint generated always as identity,
    stable_event_key text not null,
    range_id text not null,
    connection_id uuid,
    record_sequence bigint,
    firing_point_index integer,
    lane_number integer,
    shooter_number text,
    event_type text,
    event_sequence bigint,
    device_time_text text,
    annual_ticks bigint,
    received_at timestamptz not null,
    raw_text text,
    fields jsonb,
    raw_base64 text not null,
    delimiter_base64 text not null,
    raw_size_bytes integer,
    raw_sha256 text not null,
    complete boolean not null,
    partial_reason text,
    parser_version text not null,
    parsed jsonb,
    parse_error text,
    created_at timestamptz not null default now()
);

-- Keep the script safe to rerun against schemas created by earlier releases.
alter table public.sius_raw_events
    add column if not exists ingest_id bigint generated always as identity,
    add column if not exists stable_event_key text,
    add column if not exists connection_id uuid,
    add column if not exists record_sequence bigint,
    add column if not exists firing_point_index integer,
    add column if not exists shooter_number text,
    add column if not exists event_sequence bigint,
    add column if not exists device_time_text text,
    add column if not exists annual_ticks bigint,
    add column if not exists raw_text text,
    add column if not exists fields jsonb,
    add column if not exists raw_size_bytes integer,
    add column if not exists partial_reason text;

update public.sius_raw_events
set stable_event_key = event_key
where stable_event_key is null;

alter table public.sius_raw_events
    alter column stable_event_key set not null;

create unique index if not exists sius_raw_events_ingest_id_idx
    on public.sius_raw_events (ingest_id);

create index if not exists sius_raw_events_stable_event_key_idx
    on public.sius_raw_events (stable_event_key);

create index if not exists sius_raw_events_range_lane_received_idx
    on public.sius_raw_events (range_id, lane_number, received_at);

create index if not exists sius_raw_events_range_type_received_idx
    on public.sius_raw_events (range_id, event_type, received_at);

create index if not exists sius_raw_events_range_shooter_received_idx
    on public.sius_raw_events (range_id, shooter_number, received_at);

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

create index if not exists sius_shots_range_shooter_received_idx
    on public.sius_shots (range_id, shooter_number, received_at);

-- Authenticated viewer accounts and their administrator-approved firing
-- numbers. Access is intentionally many-to-many: a user may have several
-- numbers, and a number may be shared by several approved users.
create table if not exists public.sius_users (
    user_id uuid primary key references auth.users (id) on delete cascade,
    email text not null check (btrim(email) <> ''),
    role text not null default 'user' check (role in ('user', 'admin')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.sius_member_access (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null
        references public.sius_users (user_id) on delete cascade,
    range_id text not null check (btrim(range_id) <> ''),
    member_number text not null
        check (member_number ~ '^[A-Za-z0-9_-]{1,64}$'),
    status text not null default 'pending'
        check (status in ('pending', 'approved', 'rejected', 'revoked')),
    requested_at timestamptz not null default now(),
    reviewed_at timestamptz,
    reviewed_by uuid references public.sius_users (user_id),
    unique (user_id, range_id, member_number)
);

create index if not exists sius_member_access_user_scope_idx
    on public.sius_member_access (user_id, range_id, status, member_number);

create index if not exists sius_member_access_review_queue_idx
    on public.sius_member_access (range_id, status, requested_at);

create schema if not exists private;

create or replace function private.sius_sync_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.email is null or btrim(new.email) = '' then
        raise exception 'SIUS viewer accounts require an email address';
    end if;

    insert into public.sius_users (user_id, email, updated_at)
    values (new.id, lower(btrim(new.email)), now())
    on conflict (user_id) do update set
        email = excluded.email,
        updated_at = now();
    return new;
end;
$$;

drop trigger if exists sius_sync_auth_user on auth.users;
create trigger sius_sync_auth_user
after insert or update of email on auth.users
for each row execute function private.sius_sync_auth_user();

-- Backfill accounts that existed before this schema was installed.
insert into public.sius_users (user_id, email)
select users.id, lower(btrim(users.email))
from auth.users as users
where users.email is not null and btrim(users.email) <> ''
on conflict (user_id) do update set
    email = excluded.email,
    updated_at = now();

create or replace function private.sius_is_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from public.sius_users as users
        where users.user_id = (select auth.uid())
          and users.role = 'admin'
    );
$$;

create or replace function private.sius_can_read_shot(
    p_range_id text,
    p_member_number text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select private.sius_is_admin()
       or exists (
            select 1
            from public.sius_member_access as access
            where access.user_id = (select auth.uid())
              and access.range_id = p_range_id
              and access.member_number = p_member_number
              and access.status = 'approved'
       );
$$;

create or replace function private.sius_validate_access_transition()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    caller_id uuid := auth.uid();
    caller_is_admin boolean := private.sius_is_admin();
begin
    if new.id <> old.id
       or new.user_id <> old.user_id
       or new.range_id <> old.range_id
       or new.member_number <> old.member_number
       or new.requested_at <> old.requested_at then
        raise exception 'member access identity fields are immutable';
    end if;

    -- SQL editor and service-role maintenance have no end-user JWT. RLS still
    -- prevents ordinary callers from reaching this branch.
    if caller_id is null then
        return new;
    end if;

    if caller_is_admin then
        if not (
            (old.status = 'pending' and new.status in ('approved', 'rejected'))
            or (old.status = 'approved' and new.status = 'revoked')
            or (old.status in ('rejected', 'revoked') and new.status = 'approved')
        ) then
            raise exception 'invalid administrator access transition: % to %',
                old.status, new.status;
        end if;
        new.reviewed_at := now();
        new.reviewed_by := caller_id;
        return new;
    end if;

    if old.user_id <> caller_id
       or old.status <> 'rejected'
       or new.status <> 'pending' then
        raise exception 'users may only resubmit their own rejected request';
    end if;
    new.reviewed_at := null;
    new.reviewed_by := null;
    return new;
end;
$$;

drop trigger if exists sius_validate_access_transition
    on public.sius_member_access;
create trigger sius_validate_access_transition
before update on public.sius_member_access
for each row execute function private.sius_validate_access_transition();

create table if not exists public.sius_projection_state (
    name text primary key check (btrim(name) <> ''),
    normalizer_version text not null,
    last_ingest_id bigint not null default 0 check (last_ingest_id >= 0),
    processed_events bigint not null default 0 check (processed_events >= 0),
    last_success_at timestamptz,
    updated_at timestamptz not null default now()
);

create table if not exists public.sius_projection_lane_state (
    projection_name text not null
        references public.sius_projection_state (name) on delete cascade,
    range_id text not null,
    lane_number integer not null,
    firing_point_index integer not null,
    shooter_number text,
    session_id uuid not null references public.sius_sessions (id),
    phase_id uuid not null references public.sius_phases (id),
    phase_kind text not null check (phase_kind in ('sighter', 'match')),
    last_shot_number integer not null,
    last_shot_key text not null,
    last_annual_ticks bigint not null,
    last_activity_at timestamptz not null,
    match_ordinal integer not null check (match_ordinal >= 0),
    sighter_ordinal integer not null check (sighter_ordinal >= 0),
    updated_at timestamptz not null default now(),
    primary key (projection_name, range_id, lane_number)
);

create table if not exists public.sius_projection_errors (
    projection_name text not null
        references public.sius_projection_state (name) on delete cascade,
    ingest_id bigint not null,
    raw_event_key text not null references public.sius_raw_events (event_key),
    range_id text not null,
    error_kind text not null,
    error_message text not null,
    normalizer_version text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (projection_name, ingest_id)
);

create index if not exists sius_projection_errors_kind_idx
    on public.sius_projection_errors (projection_name, error_kind, ingest_id);

create or replace function public.sius_existing_shot_keys(p_shot_keys text[])
returns table (shot_key text)
language sql
stable
security invoker
set search_path = ''
as $$
    select shots.shot_key
    from public.sius_shots as shots
    where shots.shot_key = any(coalesce(p_shot_keys, array[]::text[]));
$$;

create or replace function public.sius_touch_projection(
    p_projection_name text,
    p_normalizer_version text
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    current_state public.sius_projection_state%rowtype;
begin
    if btrim(coalesce(p_projection_name, '')) = '' then
        raise exception 'projection name must not be empty';
    end if;
    if btrim(coalesce(p_normalizer_version, '')) = '' then
        raise exception 'normalizer version must not be empty';
    end if;

    insert into public.sius_projection_state (
        name,
        normalizer_version,
        last_ingest_id,
        processed_events,
        updated_at
    ) values (
        p_projection_name,
        p_normalizer_version,
        0,
        0,
        now()
    )
    on conflict (name) do nothing;

    select *
    into strict current_state
    from public.sius_projection_state
    where name = p_projection_name
    for update;

    if current_state.normalizer_version <> p_normalizer_version then
        raise exception
            'normalizer version mismatch: stored %, requested %',
            current_state.normalizer_version,
            p_normalizer_version;
    end if;

    update public.sius_projection_state
    set
        last_success_at = now(),
        updated_at = now()
    where name = p_projection_name
    returning * into current_state;

    return jsonb_build_object(
        'last_ingest_id', current_state.last_ingest_id,
        'processed_events', current_state.processed_events
    );
end;
$$;

create or replace function public.sius_commit_projection_batch(
    p_projection_name text,
    p_normalizer_version text,
    p_expected_last_ingest_id bigint,
    p_next_last_ingest_id bigint,
    p_processed_events integer,
    p_batch jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    current_state public.sius_projection_state%rowtype;
    shot_rows integer;
    distinct_shot_rows integer;
    committed_shots integer := 0;
    recorded_errors integer := 0;
begin
    if btrim(coalesce(p_projection_name, '')) = '' then
        raise exception 'projection name must not be empty';
    end if;
    if btrim(coalesce(p_normalizer_version, '')) = '' then
        raise exception 'normalizer version must not be empty';
    end if;
    if p_expected_last_ingest_id < 0
       or p_next_last_ingest_id <= p_expected_last_ingest_id then
        raise exception 'invalid projection checkpoint range';
    end if;
    if p_processed_events <= 0 then
        raise exception 'processed event count must be positive';
    end if;
    if jsonb_typeof(p_batch) <> 'object' then
        raise exception 'projection batch must be a JSON object';
    end if;
    if not exists (
        select 1
        from public.sius_raw_events
        where ingest_id = p_next_last_ingest_id
    ) then
        raise exception 'next projection checkpoint is not a raw ingest ID';
    end if;

    insert into public.sius_projection_state (
        name,
        normalizer_version,
        last_ingest_id,
        processed_events,
        updated_at
    ) values (
        p_projection_name,
        p_normalizer_version,
        0,
        0,
        now()
    )
    on conflict (name) do nothing;

    select *
    into strict current_state
    from public.sius_projection_state
    where name = p_projection_name
    for update;

    if current_state.normalizer_version <> p_normalizer_version then
        raise exception
            'normalizer version mismatch: stored %, requested %',
            current_state.normalizer_version,
            p_normalizer_version;
    end if;
    if current_state.last_ingest_id <> p_expected_last_ingest_id then
        raise exception
            'projection checkpoint conflict: stored %, expected %',
            current_state.last_ingest_id,
            p_expected_last_ingest_id;
    end if;

    select count(*), count(distinct rows.shot_key)
    into shot_rows, distinct_shot_rows
    from jsonb_to_recordset(
        coalesce(p_batch -> 'shots', '[]'::jsonb)
    ) as rows(shot_key text);

    if shot_rows <> distinct_shot_rows then
        raise exception 'projection batch contains duplicate shot keys';
    end if;
    if exists (
        select 1
        from jsonb_to_recordset(
            coalesce(p_batch -> 'shots', '[]'::jsonb)
        ) as rows(shot_key text)
        join public.sius_shots as shots using (shot_key)
    ) then
        raise exception 'projection batch contains an existing shot key';
    end if;

    insert into public.sius_sessions (
        id,
        range_id,
        lane_number,
        firing_point_index,
        shooter_number,
        started_at,
        last_activity_at,
        ended_at,
        updated_at
    )
    select
        rows.id,
        rows.range_id,
        rows.lane_number,
        rows.firing_point_index,
        rows.shooter_number,
        rows.started_at,
        rows.last_activity_at,
        null,
        now()
    from jsonb_to_recordset(
        coalesce(p_batch -> 'session_starts', '[]'::jsonb)
    ) as rows(
        id uuid,
        range_id text,
        lane_number integer,
        firing_point_index integer,
        shooter_number text,
        started_at timestamptz,
        last_activity_at timestamptz
    )
    on conflict (id) do update set
        firing_point_index = excluded.firing_point_index,
        last_activity_at = greatest(
            public.sius_sessions.last_activity_at,
            excluded.last_activity_at
        ),
        updated_at = now();

    insert into public.sius_phases (
        id,
        session_id,
        range_id,
        lane_number,
        phase_kind,
        ordinal,
        started_at,
        last_activity_at,
        ended_at,
        shot_count,
        score_sum_tenths,
        updated_at
    )
    select
        rows.id,
        rows.session_id,
        rows.range_id,
        rows.lane_number,
        rows.phase_kind,
        rows.ordinal,
        rows.started_at,
        rows.last_activity_at,
        null,
        0,
        0,
        now()
    from jsonb_to_recordset(
        coalesce(p_batch -> 'phase_starts', '[]'::jsonb)
    ) as rows(
        id uuid,
        session_id uuid,
        range_id text,
        lane_number integer,
        phase_kind text,
        ordinal integer,
        started_at timestamptz,
        last_activity_at timestamptz
    )
    on conflict (id) do update set
        last_activity_at = greatest(
            public.sius_phases.last_activity_at,
            excluded.last_activity_at
        ),
        updated_at = now();

    update public.sius_sessions as sessions
    set
        last_activity_at = greatest(
            sessions.last_activity_at,
            rows.last_activity_at
        ),
        firing_point_index = rows.firing_point_index,
        updated_at = now()
    from jsonb_to_recordset(
        coalesce(p_batch -> 'session_activity', '[]'::jsonb)
    ) as rows(
        id uuid,
        firing_point_index integer,
        last_activity_at timestamptz
    )
    where sessions.id = rows.id;

    update public.sius_sessions as sessions
    set
        ended_at = coalesce(sessions.ended_at, rows.ended_at),
        updated_at = now()
    from jsonb_to_recordset(
        coalesce(p_batch -> 'session_closures', '[]'::jsonb)
    ) as rows(id uuid, ended_at timestamptz)
    where sessions.id = rows.id;

    update public.sius_phases as phases
    set
        ended_at = coalesce(phases.ended_at, rows.ended_at),
        updated_at = now()
    from jsonb_to_recordset(
        coalesce(p_batch -> 'phase_closures', '[]'::jsonb)
    ) as rows(id uuid, ended_at timestamptz)
    where phases.id = rows.id;

    insert into public.sius_shots (
        shot_key,
        raw_event_key,
        session_id,
        phase_id,
        range_id,
        lane_number,
        firing_point_index,
        shooter_number,
        received_at,
        device_time_text,
        annual_ticks,
        event_sequence,
        phase_kind,
        shot_number,
        score_integer,
        score_tenths,
        primary_score_raw,
        secondary_score_raw,
        shot_flags_raw,
        exercise_code_raw,
        x_native,
        y_native,
        parser_version,
        payload
    )
    select
        rows.shot_key,
        rows.raw_event_key,
        rows.session_id,
        rows.phase_id,
        rows.range_id,
        rows.lane_number,
        rows.firing_point_index,
        rows.shooter_number,
        rows.received_at,
        rows.device_time_text,
        rows.annual_ticks,
        rows.event_sequence,
        rows.phase_kind,
        rows.shot_number,
        rows.score_integer,
        rows.score_tenths,
        rows.primary_score_raw,
        rows.secondary_score_raw,
        rows.shot_flags_raw,
        rows.exercise_code_raw,
        rows.x_native,
        rows.y_native,
        rows.parser_version,
        rows.payload
    from jsonb_to_recordset(
        coalesce(p_batch -> 'shots', '[]'::jsonb)
    ) as rows(
        shot_key text,
        raw_event_key text,
        session_id uuid,
        phase_id uuid,
        range_id text,
        lane_number integer,
        firing_point_index integer,
        shooter_number text,
        received_at timestamptz,
        device_time_text text,
        annual_ticks bigint,
        event_sequence integer,
        phase_kind text,
        shot_number integer,
        score_integer integer,
        score_tenths integer,
        primary_score_raw integer,
        secondary_score_raw integer,
        shot_flags_raw integer,
        exercise_code_raw integer,
        x_native numeric,
        y_native numeric,
        parser_version text,
        payload jsonb
    );
    get diagnostics committed_shots = row_count;

    with affected as (
        select distinct rows.phase_id
        from jsonb_to_recordset(
            coalesce(p_batch -> 'shots', '[]'::jsonb)
        ) as rows(phase_id uuid)
    ),
    aggregates as (
        select
            shots.phase_id,
            count(*)::integer as shot_count,
            sum(shots.score_tenths)::integer as score_sum_tenths,
            min(shots.received_at) as started_at,
            max(shots.received_at) as last_activity_at
        from public.sius_shots as shots
        join affected on affected.phase_id = shots.phase_id
        group by shots.phase_id
    )
    update public.sius_phases as phases
    set
        shot_count = aggregates.shot_count,
        score_sum_tenths = aggregates.score_sum_tenths,
        started_at = least(phases.started_at, aggregates.started_at),
        last_activity_at = greatest(
            phases.last_activity_at,
            aggregates.last_activity_at
        ),
        updated_at = now()
    from aggregates
    where phases.id = aggregates.phase_id;

    insert into public.sius_projection_lane_state (
        projection_name,
        range_id,
        lane_number,
        firing_point_index,
        shooter_number,
        session_id,
        phase_id,
        phase_kind,
        last_shot_number,
        last_shot_key,
        last_annual_ticks,
        last_activity_at,
        match_ordinal,
        sighter_ordinal,
        updated_at
    )
    select
        p_projection_name,
        rows.range_id,
        rows.lane_number,
        rows.firing_point_index,
        rows.shooter_number,
        rows.session_id,
        rows.phase_id,
        rows.phase_kind,
        rows.last_shot_number,
        rows.last_shot_key,
        rows.last_annual_ticks,
        rows.last_activity_at,
        rows.match_ordinal,
        rows.sighter_ordinal,
        now()
    from jsonb_to_recordset(
        coalesce(p_batch -> 'lane_states', '[]'::jsonb)
    ) as rows(
        range_id text,
        lane_number integer,
        firing_point_index integer,
        shooter_number text,
        session_id uuid,
        phase_id uuid,
        phase_kind text,
        last_shot_number integer,
        last_shot_key text,
        last_annual_ticks bigint,
        last_activity_at timestamptz,
        match_ordinal integer,
        sighter_ordinal integer
    )
    on conflict (projection_name, range_id, lane_number) do update set
        firing_point_index = excluded.firing_point_index,
        shooter_number = excluded.shooter_number,
        session_id = excluded.session_id,
        phase_id = excluded.phase_id,
        phase_kind = excluded.phase_kind,
        last_shot_number = excluded.last_shot_number,
        last_shot_key = excluded.last_shot_key,
        last_annual_ticks = excluded.last_annual_ticks,
        last_activity_at = excluded.last_activity_at,
        match_ordinal = excluded.match_ordinal,
        sighter_ordinal = excluded.sighter_ordinal,
        updated_at = now();

    insert into public.sius_projection_errors (
        projection_name,
        ingest_id,
        raw_event_key,
        range_id,
        error_kind,
        error_message,
        normalizer_version,
        created_at,
        updated_at
    )
    select
        p_projection_name,
        rows.ingest_id,
        rows.event_key,
        rows.range_id,
        rows.error_kind,
        rows.error_message,
        p_normalizer_version,
        now(),
        now()
    from jsonb_to_recordset(
        coalesce(p_batch -> 'errors', '[]'::jsonb)
    ) as rows(
        ingest_id bigint,
        event_key text,
        range_id text,
        error_kind text,
        error_message text
    )
    on conflict (projection_name, ingest_id) do update set
        error_kind = excluded.error_kind,
        error_message = excluded.error_message,
        normalizer_version = excluded.normalizer_version,
        updated_at = now();
    get diagnostics recorded_errors = row_count;

    update public.sius_projection_state
    set
        last_ingest_id = p_next_last_ingest_id,
        processed_events = processed_events + p_processed_events,
        last_success_at = now(),
        updated_at = now()
    where name = p_projection_name
    returning * into current_state;

    return jsonb_build_object(
        'last_ingest_id', current_state.last_ingest_id,
        'processed_events', current_state.processed_events,
        'committed_shots', committed_shots,
        'recorded_errors', recorded_errors
    );
end;
$$;

-- The uploader uses a server-side secret key, which assumes the service_role
-- inside Supabase. RLS without public policies keeps browser clients out.
alter table public.sius_raw_events enable row level security;
alter table public.sius_sessions enable row level security;
alter table public.sius_phases enable row level security;
alter table public.sius_shots enable row level security;
alter table public.sius_users enable row level security;
alter table public.sius_member_access enable row level security;
alter table public.sius_projection_state enable row level security;
alter table public.sius_projection_lane_state enable row level security;
alter table public.sius_projection_errors enable row level security;

revoke all on table public.sius_raw_events from anon, authenticated;
revoke all on table public.sius_sessions from anon, authenticated;
revoke all on table public.sius_phases from anon, authenticated;
revoke all on table public.sius_shots from anon, authenticated;
revoke all on table public.sius_users from anon, authenticated;
revoke all on table public.sius_member_access from anon, authenticated;
revoke all on table public.sius_projection_state from anon, authenticated;
revoke all on table public.sius_projection_lane_state from anon, authenticated;
revoke all on table public.sius_projection_errors from anon, authenticated;
revoke execute on function public.sius_existing_shot_keys(text[])
    from public, anon, authenticated;
revoke execute on function public.sius_touch_projection(text, text)
    from public, anon, authenticated;
revoke execute on function public.sius_commit_projection_batch(
    text,
    text,
    bigint,
    bigint,
    integer,
    jsonb
) from public, anon, authenticated;

drop policy if exists sius_users_select_own on public.sius_users;
create policy sius_users_select_own
on public.sius_users
for select
to authenticated
using (user_id = (select auth.uid()));

drop policy if exists sius_users_select_admin on public.sius_users;
create policy sius_users_select_admin
on public.sius_users
for select
to authenticated
using ((select private.sius_is_admin()));

drop policy if exists sius_member_access_select_own
    on public.sius_member_access;
create policy sius_member_access_select_own
on public.sius_member_access
for select
to authenticated
using (user_id = (select auth.uid()));

drop policy if exists sius_member_access_select_admin
    on public.sius_member_access;
create policy sius_member_access_select_admin
on public.sius_member_access
for select
to authenticated
using ((select private.sius_is_admin()));

drop policy if exists sius_member_access_insert_own
    on public.sius_member_access;
create policy sius_member_access_insert_own
on public.sius_member_access
for insert
to authenticated
with check (
    user_id = (select auth.uid())
    and status = 'pending'
    and reviewed_at is null
    and reviewed_by is null
);

drop policy if exists sius_member_access_resubmit_own
    on public.sius_member_access;
create policy sius_member_access_resubmit_own
on public.sius_member_access
for update
to authenticated
using (
    user_id = (select auth.uid())
    and status = 'rejected'
)
with check (
    user_id = (select auth.uid())
    and status = 'pending'
);

drop policy if exists sius_member_access_update_admin
    on public.sius_member_access;
create policy sius_member_access_update_admin
on public.sius_member_access
for update
to authenticated
using ((select private.sius_is_admin()))
with check ((select private.sius_is_admin()));

drop policy if exists sius_shots_select_authorized
    on public.sius_shots;
create policy sius_shots_select_authorized
on public.sius_shots
for select
to authenticated
using (private.sius_can_read_shot(range_id, shooter_number));

grant select, insert, update on table public.sius_raw_events to service_role;
grant select, insert, update on table public.sius_sessions to service_role;
grant select, insert, update on table public.sius_phases to service_role;
grant select, insert, update on table public.sius_shots to service_role;
grant select, insert, update, delete on table public.sius_users to service_role;
grant select, insert, update, delete
    on table public.sius_member_access to service_role;
grant select, insert, update on table public.sius_projection_state to service_role;
grant select, insert, update on table public.sius_projection_lane_state to service_role;
grant select, insert, update on table public.sius_projection_errors to service_role;
grant usage, select on sequence public.sius_raw_events_ingest_id_seq to service_role;
grant execute on function public.sius_existing_shot_keys(text[]) to service_role;
grant execute on function public.sius_touch_projection(text, text) to service_role;
grant execute on function public.sius_commit_projection_batch(
    text,
    text,
    bigint,
    bigint,
    integer,
    jsonb
) to service_role;

grant select on table public.sius_users to authenticated;
grant select on table public.sius_member_access to authenticated;
grant insert (user_id, range_id, member_number)
    on table public.sius_member_access to authenticated;
grant update (status)
    on table public.sius_member_access to authenticated;
grant select (
    shot_key,
    session_id,
    phase_id,
    range_id,
    lane_number,
    shooter_number,
    received_at,
    device_time_text,
    annual_ticks,
    event_sequence,
    phase_kind,
    shot_number,
    score_integer,
    score_tenths,
    primary_score_raw,
    secondary_score_raw,
    x_native,
    y_native
) on table public.sius_shots to authenticated;

revoke all on schema private from public, anon, authenticated;
grant usage on schema private to authenticated;
revoke execute on function private.sius_is_admin()
    from public, anon, authenticated;
revoke execute on function private.sius_can_read_shot(text, text)
    from public, anon, authenticated;
revoke execute on function private.sius_sync_auth_user()
    from public, anon, authenticated;
revoke execute on function private.sius_validate_access_transition()
    from public, anon, authenticated;
grant execute on function private.sius_is_admin() to authenticated;
grant execute on function private.sius_can_read_shot(text, text)
    to authenticated;

notify pgrst, 'reload schema';
