"use client";

import { useId, useState } from "react";

import { PhaseCard } from "@/components/phase-card";
import { formatDate, formatTime } from "@/lib/format";
import type { ActivityDay } from "@/lib/activity-days";

interface DayCardProps {
  day: ActivityDay;
  memberId: string;
  timezone: string;
}

export function DayCard({ day, memberId, timezone }: DayCardProps) {
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();
  const sessionLabel = `${day.sessions.length} practice ${
    day.sessions.length === 1 ? "session" : "sessions"
  }`;

  return (
    <article className="day-card">
      <header className="day-header">
        <button
          aria-controls={contentId}
          aria-expanded={expanded}
          className="day-toggle"
          onClick={() => setExpanded((current) => !current)}
          type="button"
        >
          <div>
            <p className="day-label">
              {sessionLabel} · {formatTime(day.startedAt, timezone)}–
              {formatTime(day.endedAt, timezone)}
            </p>
            <h3>{formatDate(day.startedAt, timezone)}</h3>
          </div>
          <div className="day-meta">
            <span>
              Lane{day.lanes.length === 1 ? "" : "s"} {day.lanes.join(", ")}
            </span>
            <span>{day.stats.shotCount} shots</span>
            <span>
              {day.relayCount} {day.relayCount === 1 ? "relay" : "relays"}
            </span>
            {day.sighterBlockCount > 0 ? (
              <span>
                {day.sighterBlockCount} sighter {day.sighterBlockCount === 1 ? "block" : "blocks"}
              </span>
            ) : null}
            <span className="expand-label">
              {expanded ? "Collapse day" : "Open day"}
              <span aria-hidden="true" className="expand-chevron">
                {expanded ? "−" : "+"}
              </span>
            </span>
          </div>
        </button>
      </header>

      {expanded ? (
        <div className="phase-list" id={contentId}>
          {day.sessions.flatMap((session) =>
            session.phases.map((phase) => (
              <PhaseCard
                contextLabel={`Lane ${session.laneNumber} · ${formatTime(session.startedAt, timezone)}`}
                key={phase.id}
                laneNumber={session.laneNumber}
                memberId={memberId}
                phase={phase}
                timezone={timezone}
              />
            )),
          )}
        </div>
      ) : null}
    </article>
  );
}
