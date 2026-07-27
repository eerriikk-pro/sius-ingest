import { ForgotPasswordForm } from "@/components/forgot-password-form";

export default function ForgotPasswordPage() {
  return (
    <main className="auth-single-shell">
      <section aria-labelledby="forgot-heading">
        <p className="eyebrow">Richmond Rod &amp; Gun Club</p>
        <h1 id="forgot-heading">Reset your password</h1>
        <p className="auth-page-copy">
          Enter your account email and we’ll send you a secure reset link.
        </p>
        <ForgotPasswordForm />
      </section>
    </main>
  );
}
