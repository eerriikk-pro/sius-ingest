-- Rebuild only derived practice data while preserving immutable raw events.
--
-- The next normalizer run recreates every session, phase, and canonical shot
-- from sius_raw_events beginning at ingest_id 0.

truncate table
    public.sius_projection_errors,
    public.sius_projection_lane_state,
    public.sius_shots,
    public.sius_phases,
    public.sius_sessions,
    public.sius_projection_state;
