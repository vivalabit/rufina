import { isInlineDataUrl } from "@/shared/browser-storage/data-url";

export const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function resolveApiUrl(value: string) {
  if (/^https?:\/\//i.test(value) || isInlineDataUrl(value)) return value;
  return `${apiBaseUrl}${value.startsWith("/") ? value : `/${value}`}`;
}
