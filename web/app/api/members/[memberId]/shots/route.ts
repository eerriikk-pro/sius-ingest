import { NextRequest, NextResponse } from "next/server";

import {
  getMemberActivity,
  parseDays,
  RequestValidationError,
  validateMemberId,
} from "@/lib/member-activity";
import { SupabaseReadError } from "@/lib/supabase-rest";
import type { ApiErrorResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ memberId: string }>;
}

export async function GET(
  request: NextRequest,
  context: RouteContext,
): Promise<NextResponse> {
  try {
    const { memberId: memberIdParameter } = await context.params;
    const memberId = validateMemberId(
      decodeURIComponent(memberIdParameter),
    );
    const days = parseDays(request.nextUrl.searchParams.get("days"));
    const activity = await getMemberActivity(memberId, days);
    return NextResponse.json(activity, {
      headers: {
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    if (error instanceof RequestValidationError || error instanceof URIError) {
      return errorResponse(
        error instanceof Error ? error.message : "Invalid request",
        400,
      );
    }
    if (error instanceof SupabaseReadError) {
      console.error(error);
      return errorResponse(
        "The shot database could not be read. Check the local viewer configuration.",
        502,
      );
    }

    console.error(error);
    return errorResponse(
      "The viewer could not prepare this member's activity.",
      500,
    );
  }
}

function errorResponse(message: string, status: number): NextResponse<ApiErrorResponse> {
  return NextResponse.json(
    { error: message },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
      },
    },
  );
}
