import "server-only";

export interface ViewerEnvironment {
  supabaseUrl: string;
  supabasePublishableKey: string;
  rangeId: string;
  timezone: string;
}

export function getViewerEnvironment(): ViewerEnvironment {
  const supabaseUrl =
    process.env.NEXT_PUBLIC_SUPABASE_URL?.trim() ||
    process.env.SUPABASE_URL?.trim();
  const supabasePublishableKey =
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim();
  const rangeId = process.env.SIUS_RANGE_ID?.trim();
  const timezone =
    process.env.SIUS_VIEWER_TIMEZONE?.trim() || "America/Vancouver";

  if (!supabaseUrl) {
    throw new Error("SUPABASE_URL is not configured");
  }
  if (!supabaseUrl.startsWith("https://") && !supabaseUrl.startsWith("http://")) {
    throw new Error("SUPABASE_URL must start with http:// or https://");
  }
  if (!supabasePublishableKey) {
    throw new Error("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY is not configured");
  }
  if (!rangeId) {
    throw new Error("SIUS_RANGE_ID is not configured");
  }

  try {
    new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());
  } catch {
    throw new Error(`SIUS_VIEWER_TIMEZONE is invalid: ${timezone}`);
  }

  return {
    supabaseUrl: supabaseUrl.replace(/\/+$/, ""),
    supabasePublishableKey,
    rangeId,
    timezone,
  };
}
