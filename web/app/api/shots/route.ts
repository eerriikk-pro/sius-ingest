import { NextRequest, NextResponse } from "next/server";

import { approvedMemberNumbers, getViewerContext } from "@/lib/access";
import { mayQueryMemberNumber } from "@/lib/authorization";
import { getViewerEnvironment } from "@/lib/env";
import {
  getMemberActivity,
  parseCursor,
  parseDateRange,
  RequestValidationError,
  validateMemberId,
} from "@/lib/member-activity";
import { SupabaseReadError } from "@/lib/supabase-rest";
import { createClient } from "@/lib/supabase/server";
import type { ApiErrorResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const context = await getViewerContext();
    if (!context) {
      return errorResponse("Sign in to view shots.", 401);
    }

    const environment = getViewerEnvironment();
    const memberNumber = validateMemberId(
      request.nextUrl.searchParams.get("memberNumber") ?? "",
    );
    const dateRange = parseDateRange(
      request.nextUrl.searchParams.get("from"),
      request.nextUrl.searchParams.get("to"),
      environment.timezone,
    );
    const before = parseCursor(request.nextUrl.searchParams.get("before"));
    const approved = approvedMemberNumbers(context, environment.rangeId);

    if (!mayQueryMemberNumber(context.role, approved, memberNumber)) {
      return errorResponse(
        "This member number has not been approved for your account.",
        403,
      );
    }

    const supabase = await createClient();
    const activity = await getMemberActivity(
      supabase,
      memberNumber,
      dateRange,
      before,
    );
    return NextResponse.json(activity, {
      headers: {
        "Cache-Control": "private, no-store",
      },
    });
  } catch (error) {
    if (error instanceof RequestValidationError) {
      return errorResponse(error.message, 400);
    }
    if (error instanceof SupabaseReadError) {
      console.error(error);
      return errorResponse("The authorized shot database could not be read.", 502);
    }

    console.error(error);
    return errorResponse("The viewer could not prepare this activity.", 500);
  }
}

function errorResponse(
  message: string,
  status: number,
): NextResponse<ApiErrorResponse> {
  return NextResponse.json(
    { error: message },
    {
      status,
      headers: {
        "Cache-Control": "private, no-store",
      },
    },
  );
}
