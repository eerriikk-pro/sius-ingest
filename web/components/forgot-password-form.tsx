"use client";

import Link from "next/link";
import { FormEvent, useCallback, useState } from "react";

import { TurnstileWidget } from "@/components/turnstile-widget";
import { createClient } from "@/lib/supabase/client";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [captchaResetKey, setCaptchaResetKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [complete, setComplete] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const onCaptchaTokenChange = useCallback(
    (token: string | null) => setCaptchaToken(token),
    [],
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setErrorMessage(null);
    try {
      const supabase = createClient();
      const siteUrl = (
        process.env.NEXT_PUBLIC_SITE_URL || window.location.origin
      ).replace(/\/+$/, "");
      const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
        captchaToken: captchaToken ?? undefined,
        redirectTo: `${siteUrl}/auth/callback?next=/reset-password`,
      });
      if (error) {
        setErrorMessage(error.message);
        return;
      }
      setComplete(true);
    } finally {
      setLoading(false);
      setCaptchaResetKey((value) => value + 1);
    }
  }

  return (
    <div className="auth-card">
      {complete ? (
        <div className="confirmation-panel" role="status">
          <h2>Check your email</h2>
          <p>
            If an account exists for that address, a password-reset link is on
            its way.
          </p>
          <Link className="primary-button button-link" href="/login">
            Return to sign in
          </Link>
        </div>
      ) : (
        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            <span>Email address</span>
            <input
              autoComplete="email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <TurnstileWidget
            onTokenChange={onCaptchaTokenChange}
            resetKey={captchaResetKey}
          />
          {errorMessage ? (
            <p className="form-message" role="status">
              {errorMessage}
            </p>
          ) : null}
          <button className="primary-button auth-submit" disabled={loading} type="submit">
            {loading ? "Sending…" : "Send reset link"}
          </button>
          <Link className="auth-link" href="/login">
            Back to sign in
          </Link>
        </form>
      )}
    </div>
  );
}
