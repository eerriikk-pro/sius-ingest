import { getTargetGeometry } from "./target-geometry.ts";
import type { ActivityShot, TargetKind } from "@/lib/types";

export const DEFAULT_SHOTS_PER_TARGET = 10;
export const MAX_SHOTS_PER_TARGET = 20;
export const PRINT_TARGETS_PER_PAGE = 6;
export const MIN_PRINT_ZOOM = 0.75;
export const MAX_PRINT_ZOOM = 2.25;

const TARGET_RADIUS = 100;
const TARGET_EDGE_PADDING = 4;

export interface PrintTargetGroup {
  number: number;
  shots: ActivityShot[];
  scoreTenthsTotal: number;
}

export function groupShotsForPrint(
  shots: ActivityShot[],
  shotsPerTarget: number,
): PrintTargetGroup[] {
  if (
    !Number.isInteger(shotsPerTarget) ||
    shotsPerTarget < 1 ||
    shotsPerTarget > MAX_SHOTS_PER_TARGET
  ) {
    throw new RangeError(
      `shotsPerTarget must be a whole number from 1 to ${MAX_SHOTS_PER_TARGET}`,
    );
  }

  const groups: PrintTargetGroup[] = [];
  for (let index = 0; index < shots.length; index += shotsPerTarget) {
    const groupedShots = shots.slice(index, index + shotsPerTarget);
    groups.push({
      number: groups.length + 1,
      shots: groupedShots,
      scoreTenthsTotal: groupedShots.reduce(
        (total, shot) => total + shot.scoreTenths,
        0,
      ),
    });
  }
  return groups;
}

export function paginatePrintGroups(
  groups: PrintTargetGroup[],
): PrintTargetGroup[][] {
  const pages: PrintTargetGroup[][] = [];
  for (let index = 0; index < groups.length; index += PRINT_TARGETS_PER_PAGE) {
    pages.push(groups.slice(index, index + PRINT_TARGETS_PER_PAGE));
  }
  return pages;
}

export function calculateAutoTargetZoom(
  shots: ActivityShot[],
  targetKind: TargetKind,
): number {
  const geometry = getTargetGeometry(targetKind);
  const markerExtent = geometry.shotRadius + TARGET_EDGE_PADDING;
  const furthestShotExtent = shots.reduce(
    (furthest, shot) =>
      Math.max(
        furthest,
        Math.abs(shot.xMm * 4) + markerExtent,
        Math.abs(shot.yMm * 4) + markerExtent,
      ),
    markerExtent,
  );
  const availableRadius = TARGET_RADIUS - TARGET_EDGE_PADDING;
  const fittedZoom =
    availableRadius / (geometry.baseScale * furthestShotExtent);

  return Math.max(MIN_PRINT_ZOOM, Math.min(MAX_PRINT_ZOOM, fittedZoom));
}
