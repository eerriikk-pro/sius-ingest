"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useState } from "react";

import { TurnstileWidget } from "@/components/turnstile-widget";
import { createClient } from "@/lib/supabase/client";

type AuthMode = "login" | "signup";

export function AuthForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>(
    searchParams.get("mode") === "signup" ? "signup" : "login",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [captchaResetKey, setCaptchaResetKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(
    searchParams.get("error"),
  );
  const [success, setSuccess] = useState(false);
  const onCaptchaTokenChange = useCallback(
    (token: string | null) => setCaptchaToken(token),
    [],
  );

  function changeMode(nextMode: AuthMode) {
    setMode(nextMode);
    setMessage(null);
    setSuccess(false);
    setPassword("");
    setConfirmation("");
  }

  async function handleEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setSuccess(false);

    if (mode === "signup") {
      if (password.length < 8) {
        setMessage("Use a password with at least 8 characters.");
        return;
      }
      if (password !== confirmation) {
        setMessage("The passwords do not match.");
        return;
      }
    }

    setLoading(true);
    try {
      const supabase = createClient();
      const siteUrl = (
        process.env.NEXT_PUBLIC_SITE_URL || window.location.origin
      ).replace(/\/+$/, "");
      if (mode === "signup") {
        const { error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: {
            captchaToken: captchaToken ?? undefined,
            emailRedirectTo: `${siteUrl}/auth/callback`,
          },
        });
        if (error) {
          throw error;
        }
        setSuccess(true);
        setMessage(
          "Check your email to confirm your account, then return here to sign in.",
        );
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
          options: {
            captchaToken: captchaToken ?? undefined,
          },
        });
        if (error) {
          throw error;
        }
        router.push("/");
        router.refresh();
      }
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Authentication failed.",
      );
    } finally {
      setLoading(false);
      setCaptchaResetKey((value) => value + 1);
    }
  }

  async function handleGoogle() {
    setLoading(true);
    setMessage(null);
    try {
      const supabase = createClient();
      const siteUrl = (
        process.env.NEXT_PUBLIC_SITE_URL || window.location.origin
      ).replace(/\/+$/, "");
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${siteUrl}/auth/callback`,
        },
      });
      if (error) {
        throw error;
      }
    } catch (error) {
      setLoading(false);
      setMessage(
        error instanceof Error ? error.message : "Google sign-in failed.",
      );
    }
  }

  return (
    <div className="auth-card">
      <div className="auth-tabs" role="tablist" aria-label="Account action">
        <button
          aria-selected={mode === "login"}
          className={mode === "login" ? "auth-tab-active" : ""}
          onClick={() => changeMode("login")}
          role="tab"
          type="button"
        >
          Sign in
        </button>
        <button
          aria-selected={mode === "signup"}
          className={mode === "signup" ? "auth-tab-active" : ""}
          onClick={() => changeMode("signup")}
          role="tab"
          type="button"
        >
          Create account
        </button>
      </div>

      <button
        className="google-button"
        disabled={loading}
        onClick={handleGoogle}
        type="button"
      >
        <GoogleMark />
        Continue with Google
      </button>

      <div className="auth-divider">
        <span>or use email</span>
      </div>

      <form className="auth-form" onSubmit={handleEmail}>
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
        <label>
          <span>Password</span>
          <input
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            minLength={mode === "signup" ? 8 : undefined}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        {mode === "signup" ? (
          <label>
            <span>Confirm password</span>
            <input
              autoComplete="new-password"
              minLength={8}
              onChange={(event) => setConfirmation(event.target.value)}
              required
              type="password"
              value={confirmation}
            />
          </label>
        ) : null}

        <TurnstileWidget
          onTokenChange={onCaptchaTokenChange}
          resetKey={captchaResetKey}
        />

        {message ? (
          <p
            className={success ? "form-message form-success" : "form-message"}
            role="status"
          >
            {message}
          </p>
        ) : null}

        <button className="primary-button auth-submit" disabled={loading} type="submit">
          {loading
            ? "Please wait…"
            : mode === "signup"
              ? "Create account"
              : "Sign in"}
        </button>
      </form>

      {mode === "login" ? (
        <Link className="auth-link" href="/forgot-password">
          Forgot your password?
        </Link>
      ) : (
        <p className="auth-footnote">
          After signing in, request access to your firing number. A range
          administrator must approve it before shots are visible.
        </p>
      )}
    </div>
  );
}

function GoogleMark() {
  return (
    <svg aria-hidden="true" height="18" viewBox="0 0 24 24" width="18">
      <path
        d="M21.6 12.23c0-.71-.06-1.4-.18-2.06H12v3.9h5.38a4.6 4.6 0 0 1-2 3.02v2.53h3.24c1.9-1.75 2.98-4.33 2.98-7.39Z"
        fill="#4285F4"
      />
      <path
        d="M12 22c2.7 0 4.97-.9 6.62-2.38l-3.24-2.53c-.9.6-2.05.96-3.38.96-2.6 0-4.8-1.76-5.6-4.12H3.05v2.6A10 10 0 0 0 12 22Z"
        fill="#34A853"
      />
      <path
        d="M6.4 13.93A6 6 0 0 1 6.09 12c0-.67.12-1.32.32-1.93v-2.6H3.05A10 10 0 0 0 2 12c0 1.61.38 3.14 1.05 4.53l3.36-2.6Z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.95c1.47 0 2.79.5 3.83 1.5l2.87-2.87A9.63 9.63 0 0 0 12 2a10 10 0 0 0-8.95 5.47l3.36 2.6c.79-2.36 3-4.12 5.59-4.12Z"
        fill="#EA4335"
      />
    </svg>
  );
}
