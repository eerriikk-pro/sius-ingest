import "server-only";

export interface ViewerEnvironment {
  supabaseUrl: string;
  supabaseSecretKey: string;
  rangeId?: string;
  timezone: string;
}

export function getViewerEnvironment(): ViewerEnvironment {
  const supabaseUrl = process.env.SUPABASE_URL?.trim();
  const supabaseSecretKey = process.env.SUPABASE_SECRET_KEY?.trim();
  const rangeId = process.env.SIUS_RANGE_ID?.trim() || undefined;
  const timezone =
    process.env.SIUS_VIEWER_TIMEZONE?.trim() || "America/Vancouver";

  if (!supabaseUrl) {
    throw new Error("SUPABASE_URL is not configured");
  }
  if (!supabaseUrl.startsWith("https://") && !supabaseUrl.startsWith("http://")) {
    throw new Error("SUPABASE_URL must start with http:// or https://");
  }
  if (!supabaseSecretKey) {
    throw new Error("SUPABASE_SECRET_KEY is not configured");
  }
  if (supabaseSecretKey.startsWith("sb_publishable_")) {
    throw new Error("The viewer requires a server-side Supabase secret key");
  }

  try {
    new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());
  } catch {
    throw new Error(`SIUS_VIEWER_TIMEZONE is invalid: ${timezone}`);
  }

  return {
    supabaseUrl: supabaseUrl.replace(/\/+$/, ""),
    supabaseSecretKey,
    rangeId,
    timezone,
  };
}
