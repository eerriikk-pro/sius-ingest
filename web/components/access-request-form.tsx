"use client";

import { useActionState } from "react";

import { requestMemberAccess } from "@/app/account/actions";
import { INITIAL_ACTION_STATE } from "@/lib/action-state";

export function AccessRequestForm() {
  const [state, formAction, pending] = useActionState(
    requestMemberAccess,
    INITIAL_ACTION_STATE,
  );

  return (
    <form action={formAction} className="access-request-form">
      <label>
        <span>Firing/member number</span>
        <input
          autoComplete="off"
          inputMode="numeric"
          maxLength={64}
          name="memberNumber"
          placeholder="e.g. 513"
          required
        />
      </label>
      <button className="primary-button" disabled={pending} type="submit">
        {pending ? "Submitting…" : "Request access"}
      </button>
      {state.message ? (
        <p
          className={
            state.kind === "success"
              ? "form-message form-success"
              : "form-message"
          }
          role="status"
        >
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
