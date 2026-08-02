import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";

const PAGE_SIZE = 1000;

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
  supabase: SupabaseClient,
  rangeId: string,
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
  ].join(",");

  const rows: SupabaseShotRow[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const { data, error } = await supabase
      .from("sius_shots")
      .select(select)
      .eq("range_id", rangeId)
      .eq("shooter_number", memberId)
      .gte("received_at", from.toISOString())
      .lte("received_at", to.toISOString())
      .order("received_at", { ascending: true })
      .order("annual_ticks", { ascending: true })
      .order("event_sequence", { ascending: true })
      .order("shot_number", { ascending: true })
      .range(offset, offset + PAGE_SIZE - 1)
      .returns<SupabaseShotRow[]>();
    if (error) {
      throw new SupabaseReadError(
        `Supabase could not read authorized shots: ${error.message}`,
      );
    }
    const page = data ?? [];
    rows.push(...page);
    if (page.length < PAGE_SIZE) {
      return rows;
    }
  }
}
