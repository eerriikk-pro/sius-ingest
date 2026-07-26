-- Destructive clean cutover for the pre-v0.3 experimental data.
--
-- Run schema.sql first, then run this file once. This keeps the tables and
-- permissions but removes all raw and derived SIUS data. The identity restart
-- makes the external normalizer begin at ingest_id 1.

truncate table
    public.sius_shots,
    public.sius_phases,
    public.sius_sessions,
    public.sius_raw_events
restart identity cascade;
