import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateAutoTargetZoom,
  groupShotsForPrint,
  MAX_PRINT_ZOOM,
  MAX_SHOTS_PER_TARGET,
  MIN_PRINT_ZOOM,
  paginatePrintGroups,
} from "../lib/print-layout.ts";
import type { ActivityShot } from "../lib/types.ts";

test("groups shots into targets and calculates a subtotal for each target", () => {
  const groups = groupShotsForPrint(shots(23), 10);

  assert.deepEqual(
    groups.map((group) => group.shots.length),
    [10, 10, 3],
  );
  assert.equal(groups[0].scoreTenthsTotal, 955);
  assert.equal(groups[2].scoreTenthsTotal, 276);
});

test("spills a phase longer than 60 shots onto another print page", () => {
  const pages = paginatePrintGroups(groupShotsForPrint(shots(67), 10));

  assert.equal(pages.length, 2);
  assert.equal(pages[0].length, 6);
  assert.equal(pages[1].length, 1);
  assert.equal(pages[1][0].shots.length, 7);
});

test("supports custom target group sizes and rejects unsafe values", () => {
  assert.deepEqual(
    groupShotsForPrint(shots(12), 5).map((group) => group.shots.length),
    [5, 5, 2],
  );
  assert.throws(() => groupShotsForPrint(shots(5), 0), RangeError);
  assert.throws(
    () => groupShotsForPrint(shots(5), MAX_SHOTS_PER_TARGET + 1),
    RangeError,
  );
});

test("auto zoom uses the highest safe zoom while keeping every shot visible", () => {
  assert.equal(
    calculateAutoTargetZoom(shots(1), "air-rifle"),
    MAX_PRINT_ZOOM,
  );

  const spread = shots(2);
  spread[1] = { ...spread[1], xMm: 10 };
  const fitted = calculateAutoTargetZoom(spread, "air-rifle");
  assert.ok(fitted > 1.8 && fitted < 1.9);

  const extreme = shots(2);
  extreme[1] = { ...extreme[1], xMm: 40 };
  assert.equal(
    calculateAutoTargetZoom(extreme, "air-rifle"),
    MIN_PRINT_ZOOM,
  );
});

function shots(count: number): ActivityShot[] {
  return Array.from({ length: count }, (_, index) => {
    const scoreTenths = 91 + (index % 10);
    return {
      shotKey: `shot-${index + 1}`,
      shotNumber: index + 1,
      scoreInteger: Math.floor(scoreTenths / 10),
      scoreTenths,
      score: scoreTenths / 10,
      xNative: index / 1_000_000,
      yNative: -index / 1_000_000,
      xMm: index / 1_000,
      yMm: -index / 1_000,
      receivedAt: "2026-07-25T00:00:00.000Z",
      deviceTime: "17:00:00.00",
      annualTicks: index,
      eventSequence: index,
    };
  });
}
