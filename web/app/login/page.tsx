import { redirect } from "next/navigation";

import { AuthForm } from "@/components/auth-form";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (user) {
    redirect("/");
  }

  return (
    <main className="auth-shell">
      <section className="auth-intro">
        <p className="eyebrow">Richmond Rod &amp; Gun Club</p>
        <h1>Your practice, shot by shot.</h1>
        <p>
          Sign in to review your recent SIUS sessions, relays, scores, and
          target plots.
        </p>
        <div className="auth-target" aria-hidden="true">
          <span />
        </div>
      </section>
      <section aria-labelledby="auth-heading">
        <p className="section-kicker">Member access</p>
        <h2 id="auth-heading">Welcome back</h2>
        <AuthForm />
      </section>
    </main>
  );
}
