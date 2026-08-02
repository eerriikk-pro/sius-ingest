"use server";

import { revalidatePath } from "next/cache";

import type { ActionState } from "@/lib/action-state";
import { getViewerEnvironment } from "@/lib/env";
import { validateMemberId } from "@/lib/member-activity";
import { createClient } from "@/lib/supabase/server";

export async function requestMemberAccess(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  let memberNumber: string;
  try {
    memberNumber = validateMemberId(String(formData.get("memberNumber") ?? ""));
  } catch (error) {
    return {
      kind: "error",
      message: error instanceof Error ? error.message : "Invalid member number.",
    };
  }

  const environment = getViewerEnvironment();
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return { kind: "error", message: "Your session expired. Please sign in again." };
  }

  const { data: existing, error: existingError } = await supabase
    .from("sius_member_access")
    .select("id,status")
    .eq("user_id", user.id)
    .eq("range_id", environment.rangeId)
    .eq("member_number", memberNumber)
    .maybeSingle<{ id: string; status: string }>();

  if (existingError) {
    return { kind: "error", message: existingError.message };
  }

  if (existing) {
    if (existing.status === "rejected") {
      const { data, error } = await supabase
        .from("sius_member_access")
        .update({ status: "pending" })
        .eq("id", existing.id)
        .select("id")
        .single<{ id: string }>();
      if (error) {
        return { kind: "error", message: error.message };
      }
      if (!data) {
        return { kind: "error", message: "The request could not be resubmitted." };
      }
      revalidatePath("/");
      revalidatePath("/account");
      return {
        kind: "success",
        message: `Member ${memberNumber} was resubmitted for approval.`,
      };
    }

    const labels: Record<string, string> = {
      approved: "already approved",
      pending: "already awaiting approval",
      revoked: "revoked; contact a range administrator",
    };
    return {
      kind: "error",
      message: `Member ${memberNumber} is ${labels[existing.status] ?? existing.status}.`,
    };
  }

  const { error } = await supabase.from("sius_member_access").insert({
    user_id: user.id,
    range_id: environment.rangeId,
    member_number: memberNumber,
  });
  if (error) {
    return { kind: "error", message: error.message };
  }

  revalidatePath("/");
  revalidatePath("/account");
  revalidatePath("/admin/access");
  return {
    kind: "success",
    message: `Member ${memberNumber} is awaiting administrator approval.`,
  };
}
