import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";

import { getViewerEnvironment } from "@/lib/env";
import { groupMemberShots } from "@/lib/group-shots";
import { fetchMemberShotPage } from "@/lib/supabase-rest";
import type { MemberActivity } from "@/lib/types";

export interface ActivityDateRange {
  dateFrom: string;
  dateTo: string;
  from: Date;
  toExclusive: Date;
}

export function validateMemberId(value: string): string {
  const memberId = value.trim();
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(memberId)) {
    throw new RequestValidationError(
      "Member ID must be 1–64 letters, numbers, underscores, or hyphens",
    );
  }
  return memberId;
}

export function parseDateRange(
  fromValue: string | null,
  toValue: string | null,
  timezone: string,
): ActivityDateRange | null {
  const dateFrom = fromValue?.trim() ?? "";
  const dateTo = toValue?.trim() ?? "";
  if (!dateFrom && !dateTo) {
    return null;
  }
  if (!dateFrom || !dateTo) {
    throw new RequestValidationError(
      "Choose both a start date and an end date",
    );
  }
  const from = startOfDateInTimezone(dateFrom, timezone);
  const toDate = parseCalendarDate(dateTo);
  const dayAfterTo = new Date(
    Date.UTC(toDate.year, toDate.month - 1, toDate.day + 1),
  );
  const nextDate = [
    dayAfterTo.getUTCFullYear().toString().padStart(4, "0"),
    (dayAfterTo.getUTCMonth() + 1).toString().padStart(2, "0"),
    dayAfterTo.getUTCDate().toString().padStart(2, "0"),
  ].join("-");
  const toExclusive = startOfDateInTimezone(nextDate, timezone);
  if (from >= toExclusive) {
    throw new RequestValidationError(
      "The start date must be on or before the end date",
    );
  }
  return { dateFrom, dateTo, from, toExclusive };
}

export function parseCursor(value: string | null): Date | null {
  if (value === null || value.trim() === "") {
    return null;
  }
  const cursor = new Date(value);
  if (Number.isNaN(cursor.getTime())) {
    throw new RequestValidationError("The activity cursor is invalid");
  }
  return cursor;
}

export async function getMemberActivity(
  supabase: SupabaseClient,
  memberId: string,
  dateRange: ActivityDateRange | null,
  before: Date | null,
): Promise<MemberActivity> {
  const environment = getViewerEnvironment();
  const page = await fetchMemberShotPage(
    supabase,
    environment.rangeId,
    memberId,
    {
      before,
      from: dateRange?.from ?? null,
      toExclusive: dateRange?.toExclusive ?? null,
    },
  );
  return groupMemberShots(page.rows, {
    memberId,
    dateFrom: dateRange?.dateFrom ?? null,
    dateTo: dateRange?.dateTo ?? null,
    timezone: environment.timezone,
    nextCursor: page.nextCursor,
  });
}

function startOfDateInTimezone(value: string, timezone: string): Date {
  const { year, month, day } = parseCalendarDate(value);
  const target = Date.UTC(year, month - 1, day);
  let guess = target;
  const formatter = new Intl.DateTimeFormat("en-CA-u-ca-iso8601", {
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
    minute: "2-digit",
    month: "2-digit",
    second: "2-digit",
    timeZone: timezone,
    year: "numeric",
  });

  for (let attempt = 0; attempt < 4; attempt += 1) {
    const parts = Object.fromEntries(
      formatter
        .formatToParts(new Date(guess))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, Number(part.value)]),
    );
    const observed = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
    );
    const adjustment = target - observed;
    guess += adjustment;
    if (adjustment === 0) {
      break;
    }
  }
  return new Date(guess);
}

function parseCalendarDate(value: string): {
  day: number;
  month: number;
  year: number;
} {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    throw new RequestValidationError("Dates must use the YYYY-MM-DD format");
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() + 1 !== month ||
    parsed.getUTCDate() !== day
  ) {
    throw new RequestValidationError("Choose a valid calendar date");
  }
  return { day, month, year };
}

export class RequestValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RequestValidationError";
  }
}
