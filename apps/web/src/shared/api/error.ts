export async function readApiErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    return formatApiErrorDetail(payload.detail) || formatApiErrorDetail(payload.message) || fallback;
  } catch {
    // Error responses are not guaranteed to be JSON.
  }

  return fallback;
}

export function formatApiErrorDetail(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value.map(formatApiErrorDetail).filter(Boolean).join("; ");
  }
  if (!value || typeof value !== "object") return "";

  const detail = value as Record<string, unknown>;
  if (typeof detail.msg === "string" && detail.msg.trim()) {
    const location = Array.isArray(detail.loc)
      ? detail.loc.filter((part) => part !== "body").map(String).join(".")
      : "";
    return location ? `${location}: ${detail.msg.trim()}` : detail.msg.trim();
  }

  return formatApiErrorDetail(detail.detail) || formatApiErrorDetail(detail.message);
}
