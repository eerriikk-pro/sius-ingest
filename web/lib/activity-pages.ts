import type {
  ActivitySession,
  ActivitySummary,
  MemberActivity,
} from "@/lib/types";

export function mergeActivityPages(
  current: MemberActivity,
  incoming: MemberActivity,
): MemberActivity {
  const sessions = new Map(current.sessions.map((session) => [session.id, session]));
  for (const session of incoming.sessions) {
    const existing = sessions.get(session.id);
    if (!existing || session.stats.shotCount > existing.stats.shotCount) {
      sessions.set(session.id, session);
    }
  }
  const mergedSessions = [...sessions.values()].sort(
    (left, right) =>
      right.startedAt.localeCompare(left.startedAt) ||
      right.id.localeCompare(left.id),
  );

  return {
    ...incoming,
    sessions: mergedSessions,
    summary: summarizeSessions(mergedSessions),
  };
}

export function summarizeSessions(
  sessions: ActivitySession[],
): ActivitySummary {
  let bestScore: number | null = null;
  let matchShotCount = 0;
  let relayCount = 0;
  let scoreTenthsTotal = 0;
  let shotCount = 0;
  let sighterBlockCount = 0;
  let sighterShotCount = 0;

  for (const session of sessions) {
    shotCount += session.stats.shotCount;
    scoreTenthsTotal += session.stats.scoreTenthsTotal;
    if (
      session.stats.bestScore !== null &&
      (bestScore === null || session.stats.bestScore > bestScore)
    ) {
      bestScore = session.stats.bestScore;
    }
    for (const phase of session.phases) {
      if (phase.kind === "match") {
        relayCount += 1;
        matchShotCount += phase.stats.shotCount;
      } else {
        sighterBlockCount += 1;
        sighterShotCount += phase.stats.shotCount;
      }
    }
  }

  return {
    averageScore: shotCount > 0 ? scoreTenthsTotal / shotCount / 10 : null,
    bestScore,
    matchShotCount,
    relayCount,
    scoreTenthsTotal,
    scoreTotal: scoreTenthsTotal / 10,
    sessionCount: sessions.length,
    shotCount,
    sighterBlockCount,
    sighterShotCount,
  };
}
