import "server-only";

import type { ViewerEnvironment } from "@/lib/env";

const PAGE_SIZE = 1000;

interface SupabasePhaseRow {
  id: string;
  phase_kind: string;
  ordinal: number;
  started_at: string;
  last_activity_at: string;
  ended_at: string | null;
}

interface SupabaseSessionRow {
  id: string;
  started_at: string;
  last_activity_at: string;
  ended_at: string | null;
}

export interface SupabaseShotRow {
  shot_key: string;
  session_id: string;
  phase_id: string;
  range_id: string;
  lane_number: number;
  shooter_number: string | null;
  received_at: string;
  device_time_text: string;
  annual_ticks: number;
  event_sequence: number;
  phase_kind: string;
  shot_number: number;
  score_integer: number;
  score_tenths: number;
  primary_score_raw: number;
  secondary_score_raw: number;
  x_native: number | string;
  y_native: number | string;
  phase: SupabasePhaseRow | null;
  session: SupabaseSessionRow | null;
}

export class SupabaseReadError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "SupabaseReadError";
  }
}

export async function fetchMemberShots(
  environment: ViewerEnvironment,
  memberId: string,
  from: Date,
  to: Date,
): Promise<SupabaseShotRow[]> {
  const select = [
    "shot_key",
    "session_id",
    "phase_id",
    "range_id",
    "lane_number",
    "shooter_number",
    "received_at",
    "device_time_text",
    "annual_ticks",
    "event_sequence",
    "phase_kind",
    "shot_number",
    "score_integer",
    "score_tenths",
    "primary_score_raw",
    "secondary_score_raw",
    "x_native",
    "y_native",
    "phase:sius_phases(id,phase_kind,ordinal,started_at,last_activity_at,ended_at)",
    "session:sius_sessions(id,started_at,last_activity_at,ended_at)",
  ].join(",");

  const baseQuery = new URLSearchParams({
    select,
    shooter_number: postgrestEquals(memberId),
    received_at: `gte.${from.toISOString()}`,
    order: "received_at.asc,annual_ticks.asc,event_sequence.asc,shot_number.asc",
  });
  baseQuery.append("received_at", `lte.${to.toISOString()}`);

  if (environment.rangeId) {
    baseQuery.set("range_id", postgrestEquals(environment.rangeId));
  }

  const rows: SupabaseShotRow[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const query = new URLSearchParams(baseQuery);
    query.set("limit", String(PAGE_SIZE));
    query.set("offset", String(offset));

    const page = await requestJson<SupabaseShotRow[]>(
      environment,
      `/rest/v1/sius_shots?${query}`,
    );
    rows.push(...page);
    if (page.length < PAGE_SIZE) {
      return rows;
    }
  }
}

async function requestJson<T>(
  environment: ViewerEnvironment,
  path: string,
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    apikey: environment.supabaseSecretKey,
  };
  if (!environment.supabaseSecretKey.startsWith("sb_secret_")) {
    headers.Authorization = `Bearer ${environment.supabaseSecretKey}`;
  }

  let response: Response;
  try {
    response = await fetch(`${environment.supabaseUrl}${path}`, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown network error";
    throw new SupabaseReadError(`Could not reach Supabase: ${detail}`);
  }

  if (!response.ok) {
    const detail = (await response.text()).slice(0, 500);
    throw new SupabaseReadError(
      `Supabase returned HTTP ${response.status}: ${detail}`,
      response.status,
    );
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new SupabaseReadError("Supabase returned invalid JSON");
  }
}

function postgrestEquals(value: string): string {
  if (/^[A-Za-z0-9_-]+$/.test(value)) {
    return `eq.${value}`;
  }
  const escaped = value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
  return `eq."${escaped}"`;
}
