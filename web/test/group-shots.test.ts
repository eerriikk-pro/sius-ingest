import assert from "node:assert/strict";
import test from "node:test";

import { groupMemberShots } from "../lib/group-shots.ts";
import type { SupabaseShotRow } from "../lib/supabase-rest.ts";

const FROM = new Date("2026-07-18T12:00:00.000Z");
const TO = new Date("2026-07-25T12:00:00.000Z");

test("preserves shot phase boundaries and derives visible ordinals", () => {
  const rows = [
    shotRow({
      shotKey: "sighter-1",
      phaseId: "phase-sighter",
      phaseKind: "sighter",
      shotNumber: 1,
      annualTicks: 100,
      scoreTenths: 96,
    }),
    ...Array.from({ length: 13 }, (_, index) =>
      shotRow({
        shotKey: `match-${index + 1}`,
        phaseId: "phase-match",
        phaseKind: "match",
        shotNumber: index + 1,
        annualTicks: 200 + index,
        scoreTenths: 90 + (index % 10),
      }),
    ),
  ];

  const result = groupMemberShots(rows, options());

  assert.equal(result.sessions.length, 1);
  assert.deepEqual(
    result.sessions[0].phases.map((phase) => phase.kind),
    ["sighter", "match"],
  );
  assert.equal(result.sessions[0].phases[0].ordinal, 1);
  assert.equal(result.sessions[0].phases[1].shots.length, 13);
  assert.equal(result.summary.relayCount, 1);
  assert.equal(result.summary.sighterBlockCount, 1);
  assert.equal(result.summary.matchShotCount, 13);
  assert.equal(result.summary.sighterShotCount, 1);
});

test("sorts backlog shots by SIUS counters and converts native coordinates", () => {
  const rows = [
    shotRow({
      shotKey: "later",
      shotNumber: 2,
      annualTicks: 502,
      eventSequence: 11,
      xNative: "0.00680121",
      yNative: "-0.00609518",
      scoreTenths: 73,
    }),
    shotRow({
      shotKey: "earlier",
      shotNumber: 1,
      annualTicks: 501,
      eventSequence: 10,
      xNative: "0.00199121",
      yNative: "-0.00285313",
      scoreTenths: 96,
    }),
  ];

  const result = groupMemberShots(rows, options());
  const phase = result.sessions[0].phases[0];

  assert.deepEqual(
    phase.shots.map((shot) => shot.shotKey),
    ["earlier", "later"],
  );
  assert.ok(Math.abs(phase.shots[0].xMm - 1.99121) < 1e-9);
  assert.ok(Math.abs(phase.shots[0].yMm - -2.85313) < 1e-9);
  assert.equal(phase.stats.scoreTotal, 16.9);
  assert.equal(phase.stats.averageScore, 8.45);
  assert.equal(phase.stats.bestScore, 9.6);
});

test("infers the pistol target only from the observed secondary score encoding", () => {
  const pistol = shotRow({
    shotKey: "pistol",
    primaryScoreRaw: 9,
    secondaryScoreRaw: 94,
    scoreTenths: 94,
  });
  const rifle = shotRow({
    shotKey: "rifle",
    sessionId: "session-2",
    phaseId: "phase-2",
    primaryScoreRaw: 94,
    secondaryScoreRaw: 0,
    scoreTenths: 94,
  });

  const result = groupMemberShots([pistol, rifle], options());
  const kinds = result.sessions
    .flatMap((session) => session.phases)
    .map((phase) => phase.targetKind)
    .sort();

  assert.deepEqual(kinds, ["air-pistol", "air-rifle"]);
});

function options() {
  return {
    memberId: "513",
    dateFrom: FROM.toISOString().slice(0, 10),
    dateTo: TO.toISOString().slice(0, 10),
    timezone: "America/Vancouver",
    nextCursor: null,
  };
}

interface ShotOverrides {
  shotKey?: string;
  sessionId?: string;
  phaseId?: string;
  phaseKind?: "sighter" | "match";
  shotNumber?: number;
  annualTicks?: number;
  eventSequence?: number;
  xNative?: number | string;
  yNative?: number | string;
  scoreTenths?: number;
  primaryScoreRaw?: number;
  secondaryScoreRaw?: number;
}

function shotRow(overrides: ShotOverrides = {}): SupabaseShotRow {
  const phaseKind = overrides.phaseKind ?? "match";
  const shotKey = overrides.shotKey ?? "shot-1";
  return {
    shot_key: shotKey,
    session_id: overrides.sessionId ?? "session-1",
    phase_id: overrides.phaseId ?? "phase-1",
    range_id: "default-range",
    lane_number: 6,
    shooter_number: "513",
    received_at: "2026-07-25T00:16:22.723Z",
    device_time_text: "17:16:22.75",
    annual_ticks: overrides.annualTicks ?? 100,
    event_sequence: overrides.eventSequence ?? 1,
    phase_kind: phaseKind,
    shot_number: overrides.shotNumber ?? 1,
    score_integer: Math.floor((overrides.scoreTenths ?? 94) / 10),
    score_tenths: overrides.scoreTenths ?? 94,
    primary_score_raw: overrides.primaryScoreRaw ?? 94,
    secondary_score_raw: overrides.secondaryScoreRaw ?? 0,
    x_native: overrides.xNative ?? "0.00314223",
    y_native: overrides.yNative ?? "0.00229864",
  };
}
