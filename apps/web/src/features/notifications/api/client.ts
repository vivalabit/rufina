import { apiClient } from "@/shared/api/client";

export type CriticalNotification = {
  id: string;
  severity: "critical";
  category: "parser_failure" | "parser_partial";
  source: string;
  title: string;
  description: string;
  attempts: number;
  runId: string;
  createdAt: string;
};

function normalizeCriticalNotifications(value: unknown): CriticalNotification[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is CriticalNotification => {
    if (!item || typeof item !== "object") return false;
    const candidate = item as Partial<CriticalNotification>;
    return (
      typeof candidate.id === "string"
      && candidate.severity === "critical"
      && (candidate.category === "parser_failure" || candidate.category === "parser_partial")
      && typeof candidate.source === "string"
      && typeof candidate.title === "string"
      && typeof candidate.description === "string"
      && typeof candidate.attempts === "number"
      && candidate.attempts > 0
      && typeof candidate.runId === "string"
      && typeof candidate.createdAt === "string"
    );
  });
}

export async function fetchCriticalNotifications(signal?: AbortSignal) {
  return (await apiClient.json<CriticalNotification[]>({
    path: "/notifications/critical",
    signal,
    errorMessage: "Critical notifications could not be loaded",
  }, normalizeCriticalNotifications)).data;
}

export async function deleteCriticalNotification(
  notificationId: string,
  signal?: AbortSignal,
) {
  await apiClient.empty({
    path: `/notifications/critical/${encodeURIComponent(notificationId)}`,
    method: "DELETE",
    signal,
    errorMessage: "Critical notification could not be deleted",
  });
}
