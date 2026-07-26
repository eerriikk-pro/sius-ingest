import { MemberViewer } from "@/components/member-viewer";

export default function HomePage() {
  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">Richmond Rod & Gun Club</p>
          <h1>SIUS practice viewer</h1>
          <p className="header-copy">
            Look up a firing number to review its recent sighters and match relays.
          </p>
        </div>
        <span className="local-badge">Local POC</span>
      </header>

      <MemberViewer />
    </main>
  );
}
