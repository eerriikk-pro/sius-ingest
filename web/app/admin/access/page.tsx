import { redirect } from "next/navigation";

import { AccessReviewButtons } from "@/components/access-review-buttons";
import { AccountNav } from "@/components/account-nav";
import type { AccessStatus } from "@/lib/access";
import { getViewerContext } from "@/lib/access";
import { getViewerEnvironment } from "@/lib/env";
import { createClient } from "@/lib/supabase/server";

interface AccessRow {
  id: string;
  user_id: string;
  member_number: string;
  status: AccessStatus;
  requested_at: string;
  reviewed_at: string | null;
}

interface UserRow {
  user_id: string;
  email: string;
}

export const dynamic = "force-dynamic";

export default async function AdminAccessPage() {
  const context = await getViewerContext();
  if (!context) {
    redirect("/login");
  }
  if (context.role !== "admin") {
    redirect("/");
  }

  const environment = getViewerEnvironment();
  const supabase = await createClient();
  const { data: requests, error } = await supabase
    .from("sius_member_access")
    .select("id,user_id,member_number,status,requested_at,reviewed_at")
    .eq("range_id", environment.rangeId)
    .order("requested_at", { ascending: false })
    .returns<AccessRow[]>();
  if (error) {
    throw new Error(`Could not load member requests: ${error.message}`);
  }

  const userIds = [...new Set((requests ?? []).map((record) => record.user_id))];
  let users: UserRow[] = [];
  if (userIds.length > 0) {
    const { data, error: usersError } = await supabase
      .from("sius_users")
      .select("user_id,email")
      .in("user_id", userIds)
      .returns<UserRow[]>();
    if (usersError) {
      throw new Error(`Could not load requesting users: ${usersError.message}`);
    }
    users = data ?? [];
  }
  const emailByUser = new Map(users.map((user) => [user.user_id, user.email]));
  const ordered = [...(requests ?? [])].sort(
    (left, right) =>
      Number(left.status !== "pending") - Number(right.status !== "pending") ||
      right.requested_at.localeCompare(left.requested_at),
  );

  return (
    <main className="app-shell">
      <header className="compact-header">
        <div>
          <p className="eyebrow">Richmond Rod &amp; Gun Club</p>
          <h1>Access administration</h1>
        </div>
        <AccountNav email={context.email} isAdmin />
      </header>

      <section className="admin-card">
        <div className="admin-heading">
          <div>
            <p className="section-kicker">Member verification</p>
            <h2>Shot-access requests</h2>
          </div>
          <span>{ordered.filter((record) => record.status === "pending").length} pending</span>
        </div>

        {ordered.length === 0 ? (
          <p className="muted-copy">No access requests have been submitted.</p>
        ) : (
          <div className="admin-request-list">
            {ordered.map((record) => (
              <article className="admin-request-row" key={record.id}>
                <div>
                  <strong>Member {record.member_number}</strong>
                  <span>{emailByUser.get(record.user_id) ?? record.user_id}</span>
                  <small>
                    Requested{" "}
                    {new Intl.DateTimeFormat("en-CA", {
                      dateStyle: "medium",
                      timeStyle: "short",
                      timeZone: environment.timezone,
                    }).format(new Date(record.requested_at))}
                  </small>
                </div>
                <span className={`status-badge status-${record.status}`}>
                  {record.status}
                </span>
                <AccessReviewButtons
                  requestId={record.id}
                  status={record.status}
                />
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
