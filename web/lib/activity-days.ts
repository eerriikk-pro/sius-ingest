import { summarizeSessions } from "./activity-pages.ts";
import type { ActivitySession, ActivityStats } from "@/lib/types";

export interface ActivityDay {
  dateKey: string;
  endedAt: string;
  lanes: number[];
  relayCount: number;
  sessions: ActivitySession[];
  sighterBlockCount: number;
  startedAt: string;
  stats: ActivityStats;
}

export function groupSessionsByDay(
  sessions: ActivitySession[],
  timezone: string,
): ActivityDay[] {
  const formatter = new Intl.DateTimeFormat("en-CA-u-ca-iso8601", {
    day: "2-digit",
    month: "2-digit",
    timeZone: timezone,
    year: "numeric",
  });
  const grouped = new Map<string, ActivitySession[]>();

  for (const session of sessions) {
    const parts = Object.fromEntries(
      formatter
        .formatToParts(new Date(session.startedAt))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, part.value]),
    );
    const dateKey = `${parts.year}-${parts.month}-${parts.day}`;
    const daySessions = grouped.get(dateKey) ?? [];
    daySessions.push(session);
    grouped.set(dateKey, daySessions);
  }

  return [...grouped.entries()]
    .map(([dateKey, daySessions]) => {
      const summary = summarizeSessions(daySessions);
      return {
        dateKey,
        endedAt: daySessions.reduce(
          (latest, session) =>
            session.lastActivityAt > latest ? session.lastActivityAt : latest,
          daySessions[0].lastActivityAt,
        ),
        lanes: [...new Set(daySessions.map((session) => session.laneNumber))].sort(
          (left, right) => left - right,
        ),
        relayCount: summary.relayCount,
        sessions: daySessions,
        sighterBlockCount: summary.sighterBlockCount,
        startedAt: daySessions.reduce(
          (earliest, session) =>
            session.startedAt < earliest ? session.startedAt : earliest,
          daySessions[0].startedAt,
        ),
        stats: {
          averageScore: summary.averageScore,
          bestScore: summary.bestScore,
          scoreTenthsTotal: summary.scoreTenthsTotal,
          scoreTotal: summary.scoreTotal,
          shotCount: summary.shotCount,
        },
      };
    })
    .sort((left, right) => right.dateKey.localeCompare(left.dateKey));
}
