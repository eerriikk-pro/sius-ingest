export type PhaseKind = "sighter" | "match";
export type TargetKind = "air-rifle" | "air-pistol";

export interface ActivityShot {
  shotKey: string;
  shotNumber: number;
  scoreInteger: number;
  scoreTenths: number;
  score: number;
  xNative: number;
  yNative: number;
  xMm: number;
  yMm: number;
  receivedAt: string;
  deviceTime: string;
  annualTicks: number;
  eventSequence: number;
}

export interface ActivityStats {
  shotCount: number;
  scoreTenthsTotal: number;
  scoreTotal: number;
  averageScore: number | null;
  bestScore: number | null;
}

export interface ActivityPhase {
  id: string;
  kind: PhaseKind;
  ordinal: number;
  startedAt: string;
  lastActivityAt: string;
  endedAt: string | null;
  targetKind: TargetKind;
  stats: ActivityStats;
  shots: ActivityShot[];
}

export interface ActivitySession {
  id: string;
  rangeId: string;
  laneNumber: number;
  startedAt: string;
  lastActivityAt: string;
  endedAt: string | null;
  stats: ActivityStats;
  phases: ActivityPhase[];
}

export interface ActivitySummary extends ActivityStats {
  sessionCount: number;
  relayCount: number;
  sighterBlockCount: number;
  matchShotCount: number;
  sighterShotCount: number;
}

export interface MemberActivity {
  memberId: string;
  dateFrom: string | null;
  dateTo: string | null;
  timezone: string;
  coordinateNote: string;
  summary: ActivitySummary;
  sessions: ActivitySession[];
  nextCursor: string | null;
}

export interface ApiErrorResponse {
  error: string;
}
