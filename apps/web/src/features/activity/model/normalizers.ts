import { maxStoredAppLogs } from "./constants";
import type { AppLogEntry, AppLogLevel } from "./types";

export type LogNormalizationDependencies = {
  createId: (prefix: string) => string;
  now: () => string;
};

export function normalizeStoredLogs(
  value: unknown,
  { createId, now }: LogNormalizationDependencies,
): AppLogEntry[] {
  if (!Array.isArray(value)) return [];

  return value
    .filter((entry): entry is Partial<AppLogEntry> => Boolean(entry) && typeof entry === "object")
    .map((entry) => ({
      id: typeof entry.id === "string" && entry.id ? entry.id : createId("log"),
      timestamp: typeof entry.timestamp === "string" && entry.timestamp ? entry.timestamp : now(),
      level: isAppLogLevel(entry.level) ? entry.level : "info",
      area: typeof entry.area === "string" && entry.area ? entry.area : "Application",
      message: typeof entry.message === "string" && entry.message ? entry.message : "Log entry",
      details: typeof entry.details === "string" && entry.details ? entry.details : undefined,
    }))
    .slice(0, maxStoredAppLogs);
}

export function isAppLogLevel(value: unknown): value is AppLogLevel {
  return value === "info" || value === "success" || value === "warning" || value === "error";
}
