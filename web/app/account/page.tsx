import { redirect } from "next/navigation";

import { AccessRequestForm } from "@/components/access-request-form";
import { AccountNav } from "@/components/account-nav";
import { getViewerEnvironment } from "@/lib/env";
import { getViewerContext } from "@/lib/access";

export const dynamic = "force-dynamic";

export default async function AccountPage() {
  const context = await getViewerContext();
  if (!context) {
    redirect("/login");
  }

  const environment = getViewerEnvironment();
  const access = context.access.filter(
    (record) => record.rangeId === environment.rangeId,
  );

  return (
    <main className="app-shell">
      <header className="compact-header">
        <div>
          <p className="eyebrow">Richmond Rod &amp; Gun Club</p>
          <h1>Member access</h1>
        </div>
        <AccountNav email={context.email} isAdmin={context.role === "admin"} />
      </header>

      <section className="access-layout">
        <div className="access-card">
          <p className="section-kicker">Add a number</p>
          <h2>Request shot access</h2>
          <p>
            Enter a firing or member number you use at the range. An
            administrator will verify each request before its shots become
            visible.
          </p>
          <AccessRequestForm />
        </div>

        <div className="access-card">
          <p className="section-kicker">Your requests</p>
          <h2>Access status</h2>
          {access.length === 0 ? (
            <p className="muted-copy">No member numbers requested yet.</p>
          ) : (
            <div className="access-list">
              {access.map((record) => (
                <div className="access-row" key={record.id}>
                  <div>
                    <strong>Member {record.memberNumber}</strong>
                    <span>
                      Requested{" "}
                      {new Intl.DateTimeFormat("en-CA", {
                        dateStyle: "medium",
                        timeZone: environment.timezone,
                      }).format(new Date(record.requestedAt))}
                    </span>
                  </div>
                  <span className={`status-badge status-${record.status}`}>
                    {record.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
