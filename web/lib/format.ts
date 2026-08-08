export function formatDateTime(value: string, timezone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  }).format(new Date(value));
}

export function formatDate(value: string, timezone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "full",
    timeZone: timezone,
  }).format(new Date(value));
}

export function formatTime(value: string, timezone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeStyle: "short",
    timeZone: timezone,
  }).format(new Date(value));
}

export function formatInputDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
}
