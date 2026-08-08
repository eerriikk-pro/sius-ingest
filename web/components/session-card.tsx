import { PhaseCard } from "@/components/phase-card";
import { formatDateTime } from "@/lib/format";
import type { ActivitySession } from "@/lib/types";

interface SessionCardProps {
  memberId: string;
  session: ActivitySession;
  sessionNumber: number;
  timezone: string;
}

export function SessionCard({
  memberId,
  session,
  sessionNumber,
  timezone,
}: SessionCardProps) {
  const matchRelays = session.phases.filter((phase) => phase.kind === "match").length;
  const sighterBlocks = session.phases.length - matchRelays;

  return (
    <article className="session-card">
      <header className="session-header">
        <div>
          <p className="session-label">Practice session {sessionNumber}</p>
          <h3>{formatDateTime(session.startedAt, timezone)}</h3>
        </div>
        <div className="session-meta">
          <span>Lane {session.laneNumber}</span>
          <span>{session.stats.shotCount} shots</span>
          <span>
            {matchRelays} {matchRelays === 1 ? "relay" : "relays"}
          </span>
          {sighterBlocks > 0 ? (
            <span>
              {sighterBlocks} sighter {sighterBlocks === 1 ? "block" : "blocks"}
            </span>
          ) : null}
        </div>
      </header>

      <div className="phase-list">
        {session.phases.map((phase) => (
          <PhaseCard
            key={phase.id}
            laneNumber={session.laneNumber}
            memberId={memberId}
            phase={phase}
            timezone={timezone}
          />
        ))}
      </div>
    </article>
  );
}
