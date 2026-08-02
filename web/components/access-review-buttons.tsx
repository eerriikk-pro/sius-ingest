"use client";

import { useActionState } from "react";

import { reviewMemberAccess } from "@/app/admin/access/actions";
import { INITIAL_ACTION_STATE } from "@/lib/action-state";
import type { AccessStatus } from "@/lib/access";

interface AccessReviewButtonsProps {
  requestId: string;
  status: AccessStatus;
}

export function AccessReviewButtons({
  requestId,
  status,
}: AccessReviewButtonsProps) {
  const [state, formAction, pending] = useActionState(
    reviewMemberAccess,
    INITIAL_ACTION_STATE,
  );

  const actions =
    status === "pending"
      ? [
          ["approved", "Approve"],
          ["rejected", "Reject"],
        ]
      : status === "approved"
        ? [["revoked", "Revoke"]]
        : [["approved", "Restore"]];

  return (
    <div>
      <form action={formAction} className="review-actions">
        <input name="requestId" type="hidden" value={requestId} />
        {actions.map(([value, label]) => (
          <button
            className={value === "approved" ? "approve-button" : "reject-button"}
            disabled={pending}
            key={value}
            name="decision"
            type="submit"
            value={value}
          >
            {label}
          </button>
        ))}
      </form>
      {state.message && state.kind === "error" ? (
        <p className="inline-error" role="status">
          {state.message}
        </p>
      ) : null}
    </div>
  );
}
