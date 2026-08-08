import type { TargetKind } from "@/lib/types";

export interface TargetRing {
  radius: number;
  black: boolean;
}

export interface TargetGeometry {
  baseScale: number;
  rings: readonly TargetRing[];
  shotRadius: number;
}

const RIFLE_RINGS: readonly TargetRing[] = [
  { radius: 91, black: false },
  { radius: 81, black: false },
  { radius: 71, black: false },
  { radius: 61, black: true },
  { radius: 51, black: true },
  { radius: 41, black: true },
  { radius: 31, black: true },
  { radius: 21, black: true },
  { radius: 11, black: true },
  { radius: 1, black: false },
];

const PISTOL_RINGS: readonly TargetRing[] = [
  { radius: 311, black: false },
  { radius: 279, black: false },
  { radius: 247, black: false },
  { radius: 215, black: false },
  { radius: 183, black: false },
  { radius: 151, black: false },
  { radius: 119, black: true },
  { radius: 87, black: true },
  { radius: 55, black: true },
  { radius: 23, black: true },
  { radius: 10, black: false },
];

export function getTargetGeometry(targetKind: TargetKind): TargetGeometry {
  return targetKind === "air-pistol"
    ? { baseScale: 0.3, rings: PISTOL_RINGS, shotRadius: 18 }
    : { baseScale: 1, rings: RIFLE_RINGS, shotRadius: 8 };
}
