import Link from "next/link";
import { redirect } from "next/navigation";

import { AccountNav } from "@/components/account-nav";
import { MemberViewer } from "@/components/member-viewer";
import { approvedMemberNumbers, getViewerContext } from "@/lib/access";
import { getViewerEnvironment } from "@/lib/env";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const context = await getViewerContext();
  if (!context) {
    redirect("/login");
  }
  const environment = getViewerEnvironment();
  const approved = approvedMemberNumbers(context, environment.rangeId);
  const isAdmin = context.role === "admin";

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Richmond Rod & Gun Club</p>
          <h1>SIUS practice viewer</h1>
          <p className="header-copy">
            Review recent sighters, match relays, scores, and target plots.
          </p>
        </div>
        <AccountNav email={context.email} isAdmin={isAdmin} />
      </header>

      {!isAdmin && approved.length === 0 ? (
        <section className="no-access-card">
          <div className="empty-target" aria-hidden="true">
            <span />
          </div>
          <div>
            <p className="section-kicker">Approval required</p>
            <h2>Connect a member number</h2>
            <p>
              Request the firing or member number you use at the range. Your
              shots will appear after an administrator approves it.
            </p>
            <Link className="primary-button button-link" href="/account">
              Manage member access
            </Link>
          </div>
        </section>
      ) : (
        <MemberViewer approvedMemberNumbers={approved} isAdmin={isAdmin} />
      )}
    </main>
  );
}
