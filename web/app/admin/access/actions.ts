"use server";

import { revalidatePath } from "next/cache";

import type { ActionState } from "@/lib/action-state";
import { getViewerContext } from "@/lib/access";
import { createClient } from "@/lib/supabase/server";

const DECISIONS = new Set(["approved", "rejected", "revoked"]);

export async function reviewMemberAccess(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const requestId = String(formData.get("requestId") ?? "");
  const decision = String(formData.get("decision") ?? "");
  if (!/^[0-9a-f-]{36}$/i.test(requestId) || !DECISIONS.has(decision)) {
    return { kind: "error", message: "Invalid access review request." };
  }

  const context = await getViewerContext();
  if (!context || context.role !== "admin") {
    return { kind: "error", message: "Administrator access is required." };
  }

  const supabase = await createClient();
  const { data, error } = await supabase
    .from("sius_member_access")
    .update({ status: decision })
    .eq("id", requestId)
    .select("id")
    .single<{ id: string }>();
  if (error) {
    return { kind: "error", message: error.message };
  }
  if (!data) {
    return { kind: "error", message: "The access request was not found." };
  }

  revalidatePath("/");
  revalidatePath("/account");
  revalidatePath("/admin/access");
  return { kind: "success", message: `Access ${decision}.` };
}
