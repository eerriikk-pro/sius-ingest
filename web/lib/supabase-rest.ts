import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";

const PAGE_SIZE = 1000;
const ACTIVITY_SLICE_SIZE = 200;

export interface MemberShotPageOptions {
  before: Date | null;
  from: Date | null;
  toExclusive: Date | null;
}

export interface MemberShotPage {
  nextCursor: string | null;
  rows: SupabaseShotRow[];
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

export async function fetchMemberShotPage(
  supabase: SupabaseClient,
  rangeId: string,
  memberId: string,
  options: MemberShotPageOptions,
): Promise<MemberShotPage> {
  let anchorQuery = supabase
    .from("sius_shots")
    .select("session_id,received_at")
    .eq("range_id", rangeId)
    .eq("shooter_number", memberId)
    .order("received_at", { ascending: false })
    .limit(ACTIVITY_SLICE_SIZE);

  if (options.from) {
    anchorQuery = anchorQuery.gte("received_at", options.from.toISOString());
  }
  if (options.toExclusive) {
    anchorQuery = anchorQuery.lt(
      "received_at",
      options.toExclusive.toISOString(),
    );
  }
  if (options.before) {
    anchorQuery = anchorQuery.lt("received_at", options.before.toISOString());
  }

  const { data: anchorData, error: anchorError } = await anchorQuery.returns<
    Pick<SupabaseShotRow, "session_id" | "received_at">[]
  >();
  if (anchorError) {
    throw new SupabaseReadError(
      `Supabase could not read authorized activity: ${anchorError.message}`,
    );
  }

  const anchors = anchorData ?? [];
  const sessionIds = [...new Set(anchors.map((row) => row.session_id))];
  if (sessionIds.length === 0) {
    return { nextCursor: null, rows: [] };
  }

  const rows = await fetchShotsForSessions(
    supabase,
    sessionIds,
    options.from,
    options.toExclusive,
  );
  const earliestReceivedAt = rows.reduce<string | null>(
    (earliest, row) =>
      earliest === null || row.received_at < earliest
        ? row.received_at
        : earliest,
    null,
  );

  return {
    nextCursor:
      anchors.length === ACTIVITY_SLICE_SIZE ? earliestReceivedAt : null,
    rows,
  };
}

async function fetchShotsForSessions(
  supabase: SupabaseClient,
  sessionIds: string[],
  from: Date | null,
  toExclusive: Date | null,
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
    let query = supabase
      .from("sius_shots")
      .select(select)
      .in("session_id", sessionIds)
      .order("received_at", { ascending: true })
      .order("annual_ticks", { ascending: true })
      .order("event_sequence", { ascending: true })
      .order("shot_number", { ascending: true });
    if (from) {
      query = query.gte("received_at", from.toISOString());
    }
    if (toExclusive) {
      query = query.lt("received_at", toExclusive.toISOString());
    }
    const { data, error } = await query
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
