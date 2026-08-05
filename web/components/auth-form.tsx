"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { createClient } from "@/lib/supabase/client";

export function AuthForm() {
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(
    searchParams.get("error"),
  );

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
      <button
        className="google-button"
        disabled={loading}
        onClick={handleGoogle}
        type="button"
      >
        <GoogleMark />
        {loading ? "Opening Google…" : "Continue with Google"}
      </button>

      {message ? (
        <p className="form-message auth-message" role="status">
          {message}
        </p>
      ) : null}

      <p className="auth-footnote">
        Sign in with a Google account, then request access to your firing
        number. A range administrator must approve it before shots are visible.
      </p>
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
