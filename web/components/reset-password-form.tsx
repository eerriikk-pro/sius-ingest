"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { createClient } from "@/lib/supabase/client";

export function ResetPasswordForm() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password.length < 8) {
      setMessage("Use a password with at least 8 characters.");
      return;
    }
    if (password !== confirmation) {
      setMessage("The passwords do not match.");
      return;
    }

    setLoading(true);
    setMessage(null);
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ password });
    setLoading(false);
    if (error) {
      setMessage(error.message);
      return;
    }
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="auth-card">
      <form className="auth-form" onSubmit={handleSubmit}>
        <label>
          <span>New password</span>
          <input
            autoComplete="new-password"
            minLength={8}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        <label>
          <span>Confirm new password</span>
          <input
            autoComplete="new-password"
            minLength={8}
            onChange={(event) => setConfirmation(event.target.value)}
            required
            type="password"
            value={confirmation}
          />
        </label>
        {message ? (
          <p className="form-message" role="status">
            {message}
          </p>
        ) : null}
        <button className="primary-button auth-submit" disabled={loading} type="submit">
          {loading ? "Updating…" : "Update password"}
        </button>
      </form>
    </div>
  );
}
