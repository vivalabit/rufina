import { isInlineDataUrl } from "@/shared/browser-storage/data-url";

export const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// The browser client currently runs as a single local workspace owner. Keep the
// value behind one accessor so an authenticated session can replace the source
// without changing endpoint clients.
export const apiOwnerId =
  process.env.NEXT_PUBLIC_RUFINA_OWNER_ID?.trim() || "local-owner";

export function resolveApiUrl(value: string) {
  if (/^https?:\/\//i.test(value) || isInlineDataUrl(value)) return value;
  return `${apiBaseUrl}${value.startsWith("/") ? value : `/${value}`}`;
}
