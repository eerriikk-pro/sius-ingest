import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";

import { getViewerEnvironment } from "@/lib/env";
import { groupMemberShots } from "@/lib/group-shots";
import { fetchMemberShots } from "@/lib/supabase-rest";
import type { MemberActivity } from "@/lib/types";

export const MIN_DAYS = 1;
export const MAX_DAYS = 365;
export const DEFAULT_DAYS = 7;

export function validateMemberId(value: string): string {
  const memberId = value.trim();
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(memberId)) {
    throw new RequestValidationError(
      "Member ID must be 1–64 letters, numbers, underscores, or hyphens",
    );
  }
  return memberId;
}

export function parseDays(value: string | null): number {
  if (value === null || value.trim() === "") {
    return DEFAULT_DAYS;
  }
  const days = Number(value);
  if (!Number.isInteger(days) || days < MIN_DAYS || days > MAX_DAYS) {
    throw new RequestValidationError(
      `Days must be a whole number from ${MIN_DAYS} to ${MAX_DAYS}`,
    );
  }
  return days;
}

export async function getMemberActivity(
  supabase: SupabaseClient,
  memberId: string,
  days: number,
  now = new Date(),
): Promise<MemberActivity> {
  const environment = getViewerEnvironment();
  const to = new Date(now);
  const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000);
  const rows = await fetchMemberShots(
    supabase,
    environment.rangeId,
    memberId,
    from,
    to,
  );
  return groupMemberShots(rows, {
    memberId,
    days,
    from,
    to,
    timezone: environment.timezone,
  });
}

export class RequestValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RequestValidationError";
  }
}
