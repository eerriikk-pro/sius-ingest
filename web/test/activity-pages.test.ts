import assert from "node:assert/strict";
import test from "node:test";

import { groupSessionsByDay } from "../lib/activity-days.ts";
import { mergeActivityPages, summarizeSessions } from "../lib/activity-pages.ts";
import type { ActivitySession, MemberActivity } from "../lib/types.ts";

test("merges paged sessions newest first and recalculates loaded totals", () => {
  const recent = session("recent", "2026-08-07T18:00:00.000Z", 3, "match");
  const older = session("older", "2026-08-01T18:00:00.000Z", 2, "sighter");
  const merged = mergeActivityPages(
    activity([recent], "2026-08-07T18:00:00.000Z"),
    activity([older], null),
  );

  assert.deepEqual(
    merged.sessions.map((item) => item.id),
    ["recent", "older"],
  );
  assert.equal(merged.summary.shotCount, 5);
  assert.equal(merged.summary.relayCount, 1);
  assert.equal(merged.summary.sighterBlockCount, 1);
  assert.equal(merged.nextCursor, null);
});

test("groups sessions by the range calendar day rather than UTC", () => {
  const sessions = [
    session("jan-2", "2026-01-02T18:00:00.000Z", 1, "match"),
    session("jan-1-late", "2026-01-02T06:30:00.000Z", 1, "match"),
    session("jan-1-early", "2026-01-01T18:00:00.000Z", 1, "sighter"),
  ];
  const days = groupSessionsByDay(sessions, "America/Vancouver");

  assert.deepEqual(
    days.map((day) => day.dateKey),
    ["2026-01-02", "2026-01-01"],
  );
  assert.equal(days[1].sessions.length, 2);
  assert.equal(days[1].stats.shotCount, 2);
});

function activity(
  sessions: ActivitySession[],
  nextCursor: string | null,
): MemberActivity {
  return {
    coordinateNote: "Coordinates",
    dateFrom: null,
    dateTo: null,
    memberId: "513",
    nextCursor,
    sessions,
    summary: summarizeSessions(sessions),
    timezone: "America/Vancouver",
  };
}

function session(
  id: string,
  startedAt: string,
  shotCount: number,
  kind: "match" | "sighter",
): ActivitySession {
  const scoreTenthsTotal = shotCount * 95;
  const stats = {
    averageScore: 9.5,
    bestScore: 9.5,
    scoreTenthsTotal,
    scoreTotal: scoreTenthsTotal / 10,
    shotCount,
  };
  return {
    endedAt: startedAt,
    id,
    laneNumber: 6,
    lastActivityAt: startedAt,
    phases: [
      {
        endedAt: startedAt,
        id: `${id}-phase`,
        kind,
        lastActivityAt: startedAt,
        ordinal: 1,
        shots: [],
        startedAt,
        stats,
        targetKind: "air-rifle",
      },
    ],
    rangeId: "default-range",
    startedAt,
    stats,
  };
}
