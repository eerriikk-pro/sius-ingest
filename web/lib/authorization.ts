import type { ViewerRole } from "@/lib/access";

export function mayQueryMemberNumber(
  role: ViewerRole,
  approvedMemberNumbers: readonly string[],
  requestedMemberNumber: string,
): boolean {
  return (
    role === "admin" || approvedMemberNumbers.includes(requestedMemberNumber)
  );
}
