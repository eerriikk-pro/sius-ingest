import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";

const ALLOWED_NEXT_PATHS = new Set(["/", "/account", "/reset-password"]);

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const requestedNext = url.searchParams.get("next") ?? "/";
  const next = ALLOWED_NEXT_PATHS.has(requestedNext) ? requestedNext : "/";

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(new URL(next, url.origin));
    }
  }

  const login = new URL("/login", url.origin);
  login.searchParams.set(
    "error",
    "That sign-in link is invalid or expired. Please try again.",
  );
  return NextResponse.redirect(login);
}
