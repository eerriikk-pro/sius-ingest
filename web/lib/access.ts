import "server-only";

import type { User } from "@supabase/supabase-js";

import { createClient } from "@/lib/supabase/server";

export type ViewerRole = "user" | "admin";
export type AccessStatus = "pending" | "approved" | "rejected" | "revoked";

export interface MemberAccess {
  id: string;
  userId: string;
  rangeId: string;
  memberNumber: string;
  status: AccessStatus;
  requestedAt: string;
  reviewedAt: string | null;
  reviewedBy: string | null;
}

export interface ViewerContext {
  user: User;
  email: string;
  role: ViewerRole;
  access: MemberAccess[];
}

interface UserRow {
  user_id: string;
  email: string;
  role: ViewerRole;
}

interface AccessRow {
  id: string;
  user_id: string;
  range_id: string;
  member_number: string;
  status: AccessStatus;
  requested_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
}

export async function getViewerContext(): Promise<ViewerContext | null> {
  const supabase = await createClient();
  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();

  if (userError || !user) {
    return null;
  }

  const [{ data: profile, error: profileError }, { data: access, error: accessError }] =
    await Promise.all([
      supabase
        .from("sius_users")
        .select("user_id,email,role")
        .eq("user_id", user.id)
        .single<UserRow>(),
      supabase
        .from("sius_member_access")
        .select(
          "id,user_id,range_id,member_number,status,requested_at,reviewed_at,reviewed_by",
        )
        .eq("user_id", user.id)
        .order("requested_at", { ascending: true })
        .returns<AccessRow[]>(),
    ]);

  if (profileError) {
    throw new Error(`Could not read the signed-in user profile: ${profileError.message}`);
  }
  if (accessError) {
    throw new Error(`Could not read member access: ${accessError.message}`);
  }

  return {
    user,
    email: profile.email,
    role: profile.role,
    access: (access ?? []).map(mapAccessRow),
  };
}

export function approvedMemberNumbers(
  context: ViewerContext,
  rangeId: string,
): string[] {
  return context.access
    .filter(
      (record) =>
        record.rangeId === rangeId && record.status === "approved",
    )
    .map((record) => record.memberNumber)
    .sort((left, right) =>
      left.localeCompare(right, undefined, { numeric: true }),
    );
}

export function mapAccessRow(row: AccessRow): MemberAccess {
  return {
    id: row.id,
    userId: row.user_id,
    rangeId: row.range_id,
    memberNumber: row.member_number,
    status: row.status,
    requestedAt: row.requested_at,
    reviewedAt: row.reviewed_at,
    reviewedBy: row.reviewed_by,
  };
}
