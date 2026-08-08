"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { DayCard } from "@/components/day-card";
import { groupSessionsByDay } from "@/lib/activity-days";
import { mergeActivityPages } from "@/lib/activity-pages";
import { formatInputDate } from "@/lib/format";
import type { ApiErrorResponse, MemberActivity } from "@/lib/types";

interface MemberViewerProps {
  approvedMemberNumbers: string[];
  isAdmin: boolean;
}

interface ActivityQuery {
  dateFrom: string;
  dateTo: string;
  memberId: string;
}

export function MemberViewer({
  approvedMemberNumbers,
  isAdmin,
}: MemberViewerProps) {
  const [memberId, setMemberId] = useState(
    approvedMemberNumbers.length === 1 ? approvedMemberNumbers[0] : "",
  );
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [activeQuery, setActiveQuery] = useState<ActivityQuery | null>(null);
  const [activity, setActivity] = useState<MemberActivity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingInitial, setLoadingInitial] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingMoreRef = useRef(false);
  const loadMoreTriggerRef = useRef<HTMLDivElement>(null);
  const loadMoreCallbackRef = useRef<() => Promise<void>>(async () => {});
  const requestNumber = useRef(0);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedMemberId = memberId.trim();
    if (!normalizedMemberId) {
      setError("Enter a member ID.");
      return;
    }
    if (Boolean(dateFrom) !== Boolean(dateTo)) {
      setError("Choose both a start date and an end date.");
      return;
    }
    if (dateFrom && dateTo && dateFrom > dateTo) {
      setError("The start date must be on or before the end date.");
      return;
    }

    const query = {
      dateFrom,
      dateTo,
      memberId: normalizedMemberId,
    };
    const currentRequest = ++requestNumber.current;
    setActiveQuery(query);
    setActivity(null);
    setLoadingInitial(true);
    setError(null);
    loadingMoreRef.current = false;
    setLoadingMore(false);

    try {
      const result = await requestActivity(query, null);
      if (currentRequest === requestNumber.current) {
        setActivity(result);
      }
    } catch (requestError) {
      if (currentRequest === requestNumber.current) {
        setError(messageFromError(requestError));
      }
    } finally {
      if (currentRequest === requestNumber.current) {
        setLoadingInitial(false);
      }
    }
  }

  const loadMore = useCallback(async () => {
    const cursor = activity?.nextCursor;
    if (!activeQuery || !cursor || loadingMoreRef.current) {
      return;
    }

    const currentRequest = requestNumber.current;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setError(null);
    try {
      const nextPage = await requestActivity(activeQuery, cursor);
      if (currentRequest === requestNumber.current) {
        setActivity((current) =>
          current ? mergeActivityPages(current, nextPage) : nextPage,
        );
      }
    } catch (requestError) {
      if (currentRequest === requestNumber.current) {
        setError(messageFromError(requestError));
      }
    } finally {
      if (currentRequest === requestNumber.current) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    }
  }, [activeQuery, activity?.nextCursor]);

  useEffect(() => {
    loadMoreCallbackRef.current = loadMore;
  }, [loadMore]);

  const canLoadMore = Boolean(activity?.nextCursor);
  useEffect(() => {
    const trigger = loadMoreTriggerRef.current;
    if (!canLoadMore || !trigger) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          void loadMoreCallbackRef.current();
        }
      },
      { rootMargin: "320px 0px" },
    );
    observer.observe(trigger);
    return () => observer.disconnect();
  }, [canLoadMore]);

  return (
    <>
      <section className="search-card" aria-labelledby="lookup-heading">
        <div>
          <p className="section-kicker">Member history</p>
          <h2 id="lookup-heading">
            {isAdmin ? "Find practice activity" : "Your practice activity"}
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
          <details className="date-filter">
            <summary>
              {dateFrom && dateTo ? "Custom dates active" : "Custom date range"}
            </summary>
            <div className="date-filter-fields">
              <label>
                <span>From</span>
                <input
                  name="from"
                  onChange={(event) => {
                    setDateFrom(event.target.value);
                    if (!dateTo) {
                      setDateTo(event.target.value);
                    }
                  }}
                  type="date"
                  value={dateFrom}
                />
              </label>
              <label>
                <span>To</span>
                <input
                  min={dateFrom || undefined}
                  name="to"
                  onChange={(event) => setDateTo(event.target.value)}
                  type="date"
                  value={dateTo}
                />
              </label>
              <button
                className="clear-button date-clear-button"
                disabled={!dateFrom && !dateTo}
                onClick={() => {
                  setDateFrom("");
                  setDateTo("");
                }}
                type="button"
              >
                Clear dates
              </button>
            </div>
          </details>
          <button
            className="primary-button"
            disabled={loadingInitial}
            type="submit"
          >
            {loadingInitial ? "Loading…" : "View shots"}
          </button>
        </form>
        <p className="search-note">
          Newest activity loads first. Open the date range only when you need a
          specific day or period.
        </p>
      </section>

      <div aria-live="polite">
        {error ? <p className="error-banner">{error}</p> : null}
        {loadingInitial ? <LoadingState /> : null}
      </div>

      {!loadingInitial && activity ? (
        <ActivityResults
          activity={activity}
          loadMore={loadMore}
          loadingMore={loadingMore}
          loadMoreTriggerRef={loadMoreTriggerRef}
        />
      ) : null}
    </>
  );
}

async function requestActivity(
  query: ActivityQuery,
  before: string | null,
): Promise<MemberActivity> {
  const parameters = new URLSearchParams({ memberNumber: query.memberId });
  if (query.dateFrom && query.dateTo) {
    parameters.set("from", query.dateFrom);
    parameters.set("to", query.dateTo);
  }
  if (before) {
    parameters.set("before", before);
  }
  const response = await fetch(`/api/shots?${parameters}`, {
    cache: "no-store",
  });
  const body = (await response.json()) as MemberActivity | ApiErrorResponse;
  if (!response.ok) {
    throw new Error("error" in body ? body.error : "The lookup failed.");
  }
  return body as MemberActivity;
}

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : "The lookup failed.";
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

interface ActivityResultsProps {
  activity: MemberActivity;
  loadMore: () => Promise<void>;
  loadingMore: boolean;
  loadMoreTriggerRef: React.RefObject<HTMLDivElement | null>;
}

function ActivityResults({
  activity,
  loadMore,
  loadingMore,
  loadMoreTriggerRef,
}: ActivityResultsProps) {
  const { summary } = activity;
  const days = groupSessionsByDay(activity.sessions, activity.timezone);
  const dateCopy =
    activity.dateFrom && activity.dateTo
      ? `${formatInputDate(activity.dateFrom)} to ${formatInputDate(activity.dateTo)}`
      : "Most recent to less recent";

  return (
    <section className="results" aria-labelledby="results-heading">
      <div className="results-heading-row">
        <div>
          <p className="section-kicker">
            {activity.dateFrom ? "Custom date range" : "Newest first"}
          </p>
          <h2 id="results-heading">Member {activity.memberId}</h2>
        </div>
        <p className="range-copy">
          {dateCopy} · {activity.sessions.length} practice {activity.sessions.length === 1 ? "session" : "sessions"} loaded
        </p>
      </div>

      <div className="summary-grid">
        <SummaryValue label="Shots loaded" value={summary.shotCount} />
        <SummaryValue label="Match relays" value={summary.relayCount} />
        <SummaryValue label="Match shots" value={summary.matchShotCount} />
        <SummaryValue label="Sighters" value={summary.sighterShotCount} />
        <SummaryValue label="Days loaded" value={days.length} />
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
            No normalized shots were found for member {activity.memberId}
            {activity.dateFrom ? " in this date range" : ""}.
          </p>
        </div>
      ) : (
        <div className="day-list">
          {days.map((day) => (
            <DayCard
              day={day}
              key={day.dateKey}
              memberId={activity.memberId}
              timezone={activity.timezone}
            />
          ))}
        </div>
      )}

      {activity.nextCursor ? (
        <div className="load-more" ref={loadMoreTriggerRef}>
          <button
            className="load-more-button"
            disabled={loadingMore}
            onClick={() => void loadMore()}
            type="button"
          >
            {loadingMore ? "Loading older activity…" : "Load older activity"}
          </button>
        </div>
      ) : activity.sessions.length > 0 ? (
        <p className="history-end">You’ve reached the oldest activity.</p>
      ) : null}

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
