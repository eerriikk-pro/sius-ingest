import { redirect } from "next/navigation";

import { ResetPasswordForm } from "@/components/reset-password-form";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export default async function ResetPasswordPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?error=Open+a+new+password-reset+link+to+continue.");
  }

  return (
    <main className="auth-single-shell">
      <section aria-labelledby="reset-heading">
        <p className="eyebrow">Richmond Rod &amp; Gun Club</p>
        <h1 id="reset-heading">Choose a new password</h1>
        <p className="auth-page-copy">
          Use at least eight characters and avoid reusing an old password.
        </p>
        <ResetPasswordForm />
      </section>
    </main>
  );
}
