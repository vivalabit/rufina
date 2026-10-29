import type { SearchHistoryEntry } from "../api/history-client";

export function searchHistorySummary(entry: SearchHistoryEntry) {
  const runs = entry.runs;
  const active = runs.some(
    (run) =>
      ["running", "queued"].includes(run.status) ||
      (!run.completedAt && ["completed", "partial"].includes(run.status)),
  );
  const failed = runs.filter((run) => run.status === "failed").length;
  const status = active
    ? "running"
    : failed === runs.length
      ? "failed"
      : failed ||
          runs.some(
            (run) =>
              run.status === "partial" || Object.keys(run.sourceErrors).length,
          )
        ? "partial"
        : "completed";
  const startedAt = runs.map((run) => run.startedAt).sort()[0];
  const completedAt = active
    ? null
    : runs
        .flatMap((run) => (run.completedAt ? [run.completedAt] : []))
        .sort()
        .at(-1);
  const names = [
    ...new Set(
      runs.map((run) => String(run.configSnapshot?.name || "Vacancy search")),
    ),
  ];
  return {
    name: names.join(" + "),
    status,
    startedAt,
    completedAt,
    duration: completedAt
      ? Math.max(0, (Date.parse(completedAt) - Date.parse(startedAt)) / 1000)
      : null,
    sources: [...new Set(runs.flatMap((run) => run.sources))],
    runType: runs[0]?.runType ?? "manual",
    found: runs.reduce((n, run) => n + run.jobsFound, 0),
    firstSeen: runs.reduce((n, run) => n + run.jobsDiscoveredNew, 0),
    added: runs.reduce((n, run) => n + run.jobsAdded, 0),
    filtered: runs.reduce((n, run) => n + run.jobsRejected, 0),
  };
}

export function searchDuration(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  const rounded = Math.round(seconds);
  return rounded < 60
    ? `${rounded}s`
    : `${Math.floor(rounded / 60)}m ${rounded % 60}s`;
}
