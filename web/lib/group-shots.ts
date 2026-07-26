import type {
  ActivityPhase,
  ActivitySession,
  ActivityShot,
  ActivityStats,
  MemberActivity,
  PhaseKind,
  TargetKind,
} from "@/lib/types";
import type { SupabaseShotRow } from "@/lib/supabase-rest";

const NATIVE_COORDINATE_TO_MM = 1000;

interface MutablePhase {
  id: string;
  kind: PhaseKind;
  ordinal: number;
  startedAt: string;
  lastActivityAt: string;
  endedAt: string | null;
  shots: ActivityShot[];
  pistolEncodingObserved: boolean;
}

interface MutableSession {
  id: string;
  rangeId: string;
  laneNumber: number;
  startedAt: string;
  lastActivityAt: string;
  endedAt: string | null;
  phases: Map<string, MutablePhase>;
}

export interface GroupShotsOptions {
  memberId: string;
  days: number;
  from: Date;
  to: Date;
  timezone: string;
}

export function groupMemberShots(
  rows: SupabaseShotRow[],
  options: GroupShotsOptions,
): MemberActivity {
  const sessions = new Map<string, MutableSession>();

  for (const row of rows) {
    const kind = parsePhaseKind(row.phase_kind);
    const session = sessions.get(row.session_id) ?? createSession(row);
    sessions.set(row.session_id, session);

    const phase = session.phases.get(row.phase_id) ?? createPhase(row, kind);
    session.phases.set(row.phase_id, phase);
    phase.shots.push(toActivityShot(row));
    phase.pistolEncodingObserved ||= row.secondary_score_raw > 0;
  }

  const groupedSessions = [...sessions.values()]
    .map(finalizeSession)
    .sort(compareSessionsNewestFirst);
  const allPhases = groupedSessions.flatMap((session) => session.phases);
  const allShots = allPhases.flatMap((phase) => phase.shots);
  const matchPhases = allPhases.filter((phase) => phase.kind === "match");
  const sighterPhases = allPhases.filter((phase) => phase.kind === "sighter");
  const matchShots = matchPhases.flatMap((phase) => phase.shots);
  const sighterShots = sighterPhases.flatMap((phase) => phase.shots);

  return {
    memberId: options.memberId,
    days: options.days,
    from: options.from.toISOString(),
    to: options.to.toISOString(),
    timezone: options.timezone,
    coordinateNote:
      "Target coordinates use the observed SIUS native-to-millimetre scale (×1000).",
    summary: {
      ...calculateStats(allShots),
      sessionCount: groupedSessions.length,
      relayCount: matchPhases.length,
      sighterBlockCount: sighterPhases.length,
      matchShotCount: matchShots.length,
      sighterShotCount: sighterShots.length,
    },
    sessions: groupedSessions,
  };
}

function createSession(row: SupabaseShotRow): MutableSession {
  return {
    id: row.session_id,
    rangeId: row.range_id,
    laneNumber: row.lane_number,
    startedAt: row.session?.started_at ?? row.received_at,
    lastActivityAt: row.session?.last_activity_at ?? row.received_at,
    endedAt: row.session?.ended_at ?? null,
    phases: new Map(),
  };
}

function createPhase(row: SupabaseShotRow, kind: PhaseKind): MutablePhase {
  return {
    id: row.phase_id,
    kind,
    ordinal: row.phase?.ordinal ?? 1,
    startedAt: row.phase?.started_at ?? row.received_at,
    lastActivityAt: row.phase?.last_activity_at ?? row.received_at,
    endedAt: row.phase?.ended_at ?? null,
    shots: [],
    pistolEncodingObserved: row.secondary_score_raw > 0,
  };
}

function finalizeSession(session: MutableSession): ActivitySession {
  const phases = [...session.phases.values()]
    .map(finalizePhase)
    .sort(comparePhasesOldestFirst);
  const shots = phases.flatMap((phase) => phase.shots);
  return {
    id: session.id,
    rangeId: session.rangeId,
    laneNumber: session.laneNumber,
    startedAt: session.startedAt,
    lastActivityAt: session.lastActivityAt,
    endedAt: session.endedAt,
    stats: calculateStats(shots),
    phases,
  };
}

function finalizePhase(phase: MutablePhase): ActivityPhase {
  const shots = [...phase.shots].sort(compareShotsOldestFirst);
  const targetKind: TargetKind = phase.pistolEncodingObserved
    ? "air-pistol"
    : "air-rifle";
  return {
    id: phase.id,
    kind: phase.kind,
    ordinal: phase.ordinal,
    startedAt: phase.startedAt,
    lastActivityAt: phase.lastActivityAt,
    endedAt: phase.endedAt,
    targetKind,
    stats: calculateStats(shots),
    shots,
  };
}

function toActivityShot(row: SupabaseShotRow): ActivityShot {
  const xNative = finiteNumber(row.x_native, "x_native");
  const yNative = finiteNumber(row.y_native, "y_native");
  return {
    shotKey: row.shot_key,
    shotNumber: row.shot_number,
    scoreInteger: row.score_integer,
    scoreTenths: row.score_tenths,
    score: row.score_tenths / 10,
    xNative,
    yNative,
    xMm: xNative * NATIVE_COORDINATE_TO_MM,
    yMm: yNative * NATIVE_COORDINATE_TO_MM,
    receivedAt: row.received_at,
    deviceTime: row.device_time_text,
    annualTicks: row.annual_ticks,
    eventSequence: row.event_sequence,
  };
}

function calculateStats(shots: ActivityShot[]): ActivityStats {
  const scoreTenthsTotal = shots.reduce(
    (total, shot) => total + shot.scoreTenths,
    0,
  );
  const bestTenths =
    shots.length > 0 ? Math.max(...shots.map((shot) => shot.scoreTenths)) : null;
  return {
    shotCount: shots.length,
    scoreTenthsTotal,
    scoreTotal: scoreTenthsTotal / 10,
    averageScore:
      shots.length > 0 ? scoreTenthsTotal / shots.length / 10 : null,
    bestScore: bestTenths === null ? null : bestTenths / 10,
  };
}

function compareShotsOldestFirst(a: ActivityShot, b: ActivityShot): number {
  return (
    a.annualTicks - b.annualTicks ||
    a.eventSequence - b.eventSequence ||
    a.shotNumber - b.shotNumber ||
    a.receivedAt.localeCompare(b.receivedAt)
  );
}

function comparePhasesOldestFirst(a: ActivityPhase, b: ActivityPhase): number {
  const firstA = a.shots[0];
  const firstB = b.shots[0];
  if (firstA && firstB) {
    const shotOrder = compareShotsOldestFirst(firstA, firstB);
    if (shotOrder !== 0) {
      return shotOrder;
    }
  }
  return a.startedAt.localeCompare(b.startedAt) || a.ordinal - b.ordinal;
}

function compareSessionsNewestFirst(
  a: ActivitySession,
  b: ActivitySession,
): number {
  const dateOrder = b.startedAt.localeCompare(a.startedAt);
  if (dateOrder !== 0) {
    return dateOrder;
  }
  const firstA = a.phases[0]?.shots[0];
  const firstB = b.phases[0]?.shots[0];
  if (firstA && firstB) {
    return compareShotsOldestFirst(firstB, firstA);
  }
  return b.id.localeCompare(a.id);
}

function parsePhaseKind(value: string): PhaseKind {
  if (value === "sighter" || value === "match") {
    return value;
  }
  throw new Error(`Unsupported phase kind: ${value}`);
}

function finiteNumber(value: number | string, field: string): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${field} is not a finite number`);
  }
  return parsed;
}
