"use client";

import { FormEvent, useRef, useState } from "react";

import { SessionCard } from "@/components/session-card";
import { formatDateTime } from "@/lib/format";
import type { ApiErrorResponse, MemberActivity } from "@/lib/types";

const DEFAULT_DAYS = 7;

interface MemberViewerProps {
  approvedMemberNumbers: string[];
  isAdmin: boolean;
}

export function MemberViewer({
  approvedMemberNumbers,
  isAdmin,
}: MemberViewerProps) {
  const [memberId, setMemberId] = useState(
    approvedMemberNumbers.length === 1 ? approvedMemberNumbers[0] : "",
  );
  const [days, setDays] = useState(DEFAULT_DAYS);
  const [activity, setActivity] = useState<MemberActivity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestNumber = useRef(0);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedMemberId = memberId.trim();
    if (!normalizedMemberId) {
      setError("Enter a member ID.");
      return;
    }
    if (!Number.isInteger(days) || days < 1 || days > 365) {
      setError("Days must be a whole number from 1 to 365.");
      return;
    }

    const currentRequest = ++requestNumber.current;
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `/api/shots?memberNumber=${encodeURIComponent(normalizedMemberId)}&days=${days}`,
        {
          cache: "no-store",
        },
      );
      const body = (await response.json()) as MemberActivity | ApiErrorResponse;
      if (!response.ok) {
        throw new Error("error" in body ? body.error : "The lookup failed.");
      }
      if (currentRequest !== requestNumber.current) {
        return;
      }

      const result = body as MemberActivity;
      setActivity(result);
    } catch (requestError) {
      if (currentRequest !== requestNumber.current) {
        return;
      }
      setActivity(null);
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The lookup failed.",
      );
    } finally {
      if (currentRequest === requestNumber.current) {
        setLoading(false);
      }
    }
  }

  return (
    <>
      <section className="search-card" aria-labelledby="lookup-heading">
        <div>
          <p className="section-kicker">Member history</p>
          <h2 id="lookup-heading">
            {isAdmin ? "Find recent practice" : "Your recent practice"}
          </h2>
        </div>
        <form className="search-form" onSubmit={handleSubmit}>
          <label>
            <span>Member ID</span>
            {!isAdmin && approvedMemberNumbers.length > 1 ? (
              <select
                name="memberId"
                onChange={(event) => setMemberId(event.target.value)}
                required
                value={memberId}
              >
                <option value="">Select a member</option>
                {approvedMemberNumbers.map((number) => (
                  <option key={number} value={number}>
                    {number}
                  </option>
                ))}
              </select>
            ) : (
              <input
                autoComplete="off"
                inputMode="numeric"
                maxLength={64}
                name="memberId"
                onChange={(event) => setMemberId(event.target.value)}
                placeholder="e.g. 513"
                readOnly={!isAdmin && approvedMemberNumbers.length === 1}
                value={memberId}
              />
            )}
          </label>
          <label className="days-field">
            <span>Past days</span>
            <input
              max={365}
              min={1}
              name="days"
              onChange={(event) => setDays(Number(event.target.value))}
              type="number"
              value={days}
            />
          </label>
          <button className="primary-button" disabled={loading} type="submit">
            {loading ? "Loading…" : "View shots"}
          </button>
        </form>
        <p className="search-note">
          Results are read-only and limited by Supabase row-level security.
        </p>
      </section>

      <div aria-live="polite">
        {error ? <p className="error-banner">{error}</p> : null}
        {loading ? <LoadingState /> : null}
      </div>

      {!loading && activity ? <ActivityResults activity={activity} /> : null}
    </>
  );
}

function LoadingState() {
  return (
    <section className="loading-card" aria-label="Loading member activity">
      <span className="loading-pulse" />
      <span className="loading-line loading-line-wide" />
      <span className="loading-line" />
    </section>
  );
}

function ActivityResults({ activity }: { activity: MemberActivity }) {
  const { summary } = activity;

  return (
    <section className="results" aria-labelledby="results-heading">
      <div className="results-heading-row">
        <div>
          <p className="section-kicker">
            Past {activity.days} {activity.days === 1 ? "day" : "days"}
          </p>
          <h2 id="results-heading">Member {activity.memberId}</h2>
        </div>
        <p className="range-copy">
          {formatDateTime(activity.from, activity.timezone)} to{" "}
          {formatDateTime(activity.to, activity.timezone)}
        </p>
      </div>

      <div className="summary-grid">
        <SummaryValue label="Shots" value={summary.shotCount} />
        <SummaryValue label="Match relays" value={summary.relayCount} />
        <SummaryValue
          label="Match shots"
          value={summary.matchShotCount}
        />
        <SummaryValue
          label="Sighters"
          value={summary.sighterShotCount}
        />
        <SummaryValue label="Sessions" value={summary.sessionCount} />
        <SummaryValue
          label="Best"
          value={summary.bestScore === null ? "—" : summary.bestScore.toFixed(1)}
        />
      </div>

      {activity.sessions.length === 0 ? (
        <div className="empty-state">
          <div className="empty-target" aria-hidden="true">
            <span />
          </div>
          <h3>No shots found</h3>
          <p>
            There are no normalized shots for member {activity.memberId} in this
            time window.
          </p>
        </div>
      ) : (
        <div className="session-list">
          {activity.sessions.map((session, index) => (
            <SessionCard
              key={session.id}
              session={session}
              sessionNumber={activity.sessions.length - index}
              timezone={activity.timezone}
            />
          ))}
        </div>
      )}

      <p className="coordinate-note">{activity.coordinateNote}</p>
    </section>
  );
}

function SummaryValue({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div className="summary-value">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}
