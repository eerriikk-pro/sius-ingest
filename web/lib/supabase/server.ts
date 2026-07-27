import "server-only";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

import { getViewerEnvironment } from "@/lib/env";

export async function createClient() {
  const environment = getViewerEnvironment();
  const cookieStore = await cookies();

  return createServerClient(
    environment.supabaseUrl,
    environment.supabasePublishableKey,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            for (const { name, value, options } of cookiesToSet) {
              cookieStore.set(name, value, options);
            }
          } catch {
            // Server Components cannot write cookies. proxy.ts refreshes the
            // session and applies updated cookies to the response.
          }
        },
      },
    },
  );
}
