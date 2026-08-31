"use client";

import { useMemo, useState } from "react";
import {
  ChevronDown,
  CircleCheck,
  CircleX,
  FileText,
  Info,
  RotateCcw,
  Search,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AppLogEntry, AppLogLevel } from "@/features/activity/model/types";
import { cn } from "@/lib/utils";

export type { AppLogEntry, AppLogLevel } from "@/features/activity/model/types";

type LogLevelFilter = "all" | AppLogLevel;

type LogLevelPresentation = {
  label: string;
  pluralLabel: string;
  icon: LucideIcon;
  badgeClassName: string;
  filterActiveClassName: string;
  iconClassName: string;
  rowClassName: string;
};

const logLevelOrder: AppLogLevel[] = ["error", "warning", "success", "info"];

const logLevelPresentation: Record<AppLogLevel, LogLevelPresentation> = {
  info: {
    label: "Info",
    pluralLabel: "Info",
    icon: Info,
    badgeClassName: "border-[#bfdbfe] bg-[#eff6ff] text-[#1d4ed8]",
    filterActiveClassName: "border-[#2563eb] bg-[#eff6ff] text-[#1d4ed8] shadow-sm",
    iconClassName: "border-[#bfdbfe] bg-[#eff6ff] text-[#2563eb]",
    rowClassName: "border-l-[#2563eb] hover:border-[#93c5fd] hover:bg-[#f8fbff]",
  },
  success: {
    label: "Success",
    pluralLabel: "Success",
    icon: CircleCheck,
    badgeClassName: "border-[#bbf7d0] bg-[#f0fdf4] text-[#15803d]",
    filterActiveClassName: "border-[#16a34a] bg-[#f0fdf4] text-[#15803d] shadow-sm",
    iconClassName: "border-[#bbf7d0] bg-[#f0fdf4] text-[#16a34a]",
    rowClassName: "border-l-[#16a34a] hover:border-[#86efac] hover:bg-[#f8fff9]",
  },
  warning: {
    label: "Warning",
    pluralLabel: "Warnings",
    icon: TriangleAlert,
    badgeClassName: "border-[#fde68a] bg-[#fffbeb] text-[#a16207]",
    filterActiveClassName: "border-[#d97706] bg-[#fffbeb] text-[#a16207] shadow-sm",
    iconClassName: "border-[#fde68a] bg-[#fffbeb] text-[#d97706]",
    rowClassName: "border-l-[#d97706] bg-[#fffdf7] hover:border-[#fcd34d] hover:bg-[#fffbeb]",
  },
  error: {
    label: "Error",
    pluralLabel: "Errors",
    icon: CircleX,
    badgeClassName: "border-[#fecaca] bg-[#fef2f2] text-[#b91c1c]",
    filterActiveClassName: "border-[#dc2626] bg-[#fef2f2] text-[#b91c1c] shadow-sm",
    iconClassName: "border-[#fecaca] bg-[#fef2f2] text-[#dc2626]",
    rowClassName: "border-l-[#dc2626] bg-[#fffafa] hover:border-[#fca5a5] hover:bg-[#fef2f2]",
  },
};

function parseLogDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatLogTime(value: string) {
  const date = parseLogDate(value);
  if (!date) return "--:--:--";

  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatLogDateTime(value: string) {
  const date = parseLogDate(value);
  if (!date) return "Time unknown";

  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function getLocalDateKey(value: string) {
  const date = parseLogDate(value);
  if (!date) return "unknown";

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function startOfLocalDay(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function formatLogDateLabel(value: string) {
  const date = parseLogDate(value);
  if (!date) return "Date unknown";

  const today = startOfLocalDay(new Date());
  const target = startOfLocalDay(date);
  const dayDifference = Math.round((today.getTime() - target.getTime()) / 86_400_000);

  if (dayDifference === 0) return "Today";
  if (dayDifference === 1) return "Yesterday";

  return date.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    ...(date.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}),
  });
}

export function LogsView({ logs, onClear }: { logs: AppLogEntry[]; onClear: () => void }) {
  const [query, setQuery] = useState("");
  const [levelFilter, setLevelFilter] = useState<LogLevelFilter>("all");
  const [areaFilter, setAreaFilter] = useState("all");

  const areas = useMemo(
    () => Array.from(new Set(logs.map((log) => log.area))).sort((left, right) => left.localeCompare(right)),
    [logs],
  );

  const levelCounts = useMemo(
    () => logs.reduce<Record<AppLogLevel, number>>(
      (counts, log) => ({ ...counts, [log.level]: counts[log.level] + 1 }),
      { info: 0, success: 0, warning: 0, error: 0 },
    ),
    [logs],
  );

  const normalizedQuery = query.trim().toLowerCase();
  const filteredLogs = useMemo(
    () => logs.filter((log) => {
      if (levelFilter !== "all" && log.level !== levelFilter) return false;
      if (areaFilter !== "all" && log.area !== areaFilter) return false;
      if (!normalizedQuery) return true;

      return [log.area, log.message, log.details]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(normalizedQuery));
    }),
    [areaFilter, levelFilter, logs, normalizedQuery],
  );

  const groupedLogs = useMemo(() => {
    const groups = new Map<string, { label: string; logs: AppLogEntry[] }>();

    for (const log of filteredLogs) {
      const key = getLocalDateKey(log.timestamp);
      const existingGroup = groups.get(key);
      if (existingGroup) {
        existingGroup.logs.push(log);
      } else {
        groups.set(key, { label: formatLogDateLabel(log.timestamp), logs: [log] });
      }
    }

    return Array.from(groups.values());
  }, [filteredLogs]);

  function resetFilters() {
    setQuery("");
    setLevelFilter("all");
    setAreaFilter("all");
  }

  return (
    <section className="job-scroll flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-4 flex shrink-0 flex-col gap-3 md:flex-row md:items-start md:justify-between 2xl:mb-5">
        <div>
          <h1 className="page-title text-[24px] leading-tight text-foreground sm:text-[27px] 2xl:text-[31px]">
            Activity &amp; logs
          </h1>
          <p className="mt-1 text-[13px] text-muted 2xl:mt-1.5 2xl:text-base">
            Search, filter, and inspect local application and parser activity
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          className="h-10 w-full rounded-md border border-border bg-white px-4 text-[13px] text-[#1d1e1c] hover:border-[#fecaca] hover:bg-[#fef2f2] hover:text-[#b91c1c] md:w-auto 2xl:h-11"
          disabled={logs.length === 0}
          onClick={onClear}
        >
          <Trash2 className="h-4 w-4" />
          Clear logs
        </Button>
      </header>

      <div className="panel flex min-h-[430px] max-w-[1220px] flex-1 flex-col overflow-hidden p-0">
        {logs.length === 0 ? (
          <div className="grid min-h-[430px] place-items-center px-4 text-center">
            <div>
              <FileText className="mx-auto h-8 w-8 text-muted" />
              <h2 className="mt-3 text-base font-bold text-foreground">No activity yet</h2>
              <p className="mt-1 max-w-[360px] text-sm leading-6 text-muted">
                Run a vacancy search or change settings to create log entries.
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="shrink-0 border-b border-[#e9dfd3] bg-[#fffdfb] px-3 py-3 sm:px-4 2xl:px-5">
              <div className="grid gap-2.5 lg:grid-cols-[minmax(260px,1fr)_220px_auto] lg:items-center">
                <label className="relative block">
                  <span className="sr-only">Search activity</span>
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search messages or details..."
                    aria-label="Search activity"
                    className="h-10 w-full rounded-md border border-border bg-white pl-9 pr-9 text-[13px] outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/15"
                  />
                  {query ? (
                    <button
                      type="button"
                      onClick={() => setQuery("")}
                      aria-label="Clear activity search"
                      className="absolute right-2 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                </label>

                <label className="relative block">
                  <span className="sr-only">Filter activity area</span>
                  <select
                    value={areaFilter}
                    onChange={(event) => setAreaFilter(event.target.value)}
                    aria-label="Filter activity area"
                    className="h-10 w-full appearance-none rounded-md border border-border bg-white px-3 pr-9 text-[13px] font-semibold text-[#4a4a47] outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/15"
                  >
                    <option value="all">All areas</option>
                    {areas.map((area) => <option key={area} value={area}>{area}</option>)}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                </label>

                <p aria-live="polite" className="text-xs font-semibold text-muted lg:text-right">
                  {filteredLogs.length} of {logs.length} {logs.length === 1 ? "event" : "events"}
                </p>
              </div>

              <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Filter activity by level">
                <button
                  type="button"
                  aria-pressed={levelFilter === "all"}
                  onClick={() => setLevelFilter("all")}
                  className={cn(
                    "inline-flex h-8 items-center gap-2 rounded-full border px-3 text-xs font-bold transition",
                    levelFilter === "all"
                      ? "border-[#1d1e1c] bg-[#1d1e1c] text-white shadow-sm"
                      : "border-[#dfd6cc] bg-white text-[#4a4a47] hover:border-[#a5a19c] hover:text-foreground",
                  )}
                >
                  All <span className={cn("tabular-nums", levelFilter === "all" ? "text-white/75" : "text-muted")}>{logs.length}</span>
                </button>
                {logLevelOrder.map((level) => {
                  const presentation = logLevelPresentation[level];
                  const Icon = presentation.icon;
                  const isSelected = levelFilter === level;

                  return (
                    <button
                      key={level}
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() => setLevelFilter(isSelected ? "all" : level)}
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-bold transition",
                        isSelected
                          ? presentation.filterActiveClassName
                          : "border-[#dfd6cc] bg-white text-[#4a4a47] hover:border-[#a5a19c] hover:text-foreground",
                      )}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {presentation.pluralLabel}
                      <span className={cn("tabular-nums", isSelected ? "opacity-70" : "text-muted")}>{levelCounts[level]}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="job-scroll min-h-0 flex-1 overflow-y-auto bg-[#fffdfb] px-3 pb-5 sm:px-4 2xl:px-5">
              {groupedLogs.length === 0 ? (
                <div className="grid min-h-[300px] place-items-center px-4 text-center">
                  <div>
                    <Search className="mx-auto h-7 w-7 text-muted" />
                    <h2 className="mt-3 text-base font-bold text-foreground">No matching activity</h2>
                    <p className="mt-1 max-w-[380px] text-sm leading-6 text-muted">
                      Try another search term or reset the active filters.
                    </p>
                    <Button type="button" variant="ghost" className="mt-4 h-9 border border-border bg-white px-4 text-xs" onClick={resetFilters}>
                      <RotateCcw className="h-3.5 w-3.5" />
                      Reset filters
                    </Button>
                  </div>
                </div>
              ) : (
                groupedLogs.map((group) => (
                  <section key={`${group.label}-${group.logs[0]?.id}`} aria-label={group.label}>
                    <div className="sticky top-0 z-10 flex items-center gap-3 bg-[#fffdfb]/95 py-3 backdrop-blur-sm">
                      <h2 className="shrink-0 text-[11px] font-bold uppercase tracking-[0.12em] text-muted">{group.label}</h2>
                      <div className="h-px flex-1 bg-[#e9dfd3]" />
                    </div>

                    <ol className="space-y-2.5">
                      {group.logs.map((log) => {
                        const presentation = logLevelPresentation[log.level];
                        const Icon = presentation.icon;

                        return (
                          <li key={log.id} className="grid gap-x-3 md:grid-cols-[76px_34px_minmax(0,1fr)]">
                            <time dateTime={log.timestamp} className="hidden pt-3 text-right font-mono text-[11px] font-semibold tabular-nums text-[#777571] md:block">
                              {formatLogTime(log.timestamp)}
                            </time>

                            <div className="hidden pt-2 md:flex md:justify-center" aria-hidden="true">
                              <span className={cn("grid h-8 w-8 place-items-center rounded-full border", presentation.iconClassName)}>
                                <Icon className="h-4 w-4" />
                              </span>
                            </div>

                            <article
                              aria-label={`${presentation.label} · ${log.area}`}
                              className={cn(
                                "min-w-0 rounded-md border border-[#e5ddd3] border-l-[3px] bg-white px-3.5 py-3 shadow-[0_3px_12px_rgba(74,74,71,0.045)] transition sm:px-4",
                                presentation.rowClassName,
                              )}
                            >
                              <div className="flex min-w-0 flex-wrap items-center gap-2">
                                <span className={cn("inline-flex h-6 items-center gap-1.5 rounded-full border px-2 text-[10px] font-bold uppercase tracking-[0.06em]", presentation.badgeClassName)}>
                                  <Icon className="h-3 w-3" />
                                  {presentation.label}
                                </span>
                                <span className="inline-flex h-6 items-center rounded-full bg-[#f3eee8] px-2 text-[11px] font-bold text-[#4a4a47]">
                                  {log.area}
                                </span>
                                <time dateTime={log.timestamp} className="ml-auto font-mono text-[10px] font-semibold tabular-nums text-[#777571] md:hidden">
                                  {formatLogDateTime(log.timestamp)}
                                </time>
                              </div>

                              <p className="mt-2 text-[13px] font-semibold leading-5 text-foreground sm:text-sm 2xl:text-[15px]">
                                {log.message}
                              </p>

                              {log.details ? (
                                <details className="group mt-2 border-t border-[#e9dfd3] pt-2">
                                  <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-[11px] font-bold text-muted transition hover:text-foreground [&::-webkit-details-marker]:hidden">
                                    View details
                                    <ChevronDown className="h-3.5 w-3.5 transition group-open:rotate-180" />
                                  </summary>
                                  <pre className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-[#f7f3ee] px-3 py-2 font-mono text-[11px] leading-5 text-[#4a4a47] [overflow-wrap:anywhere]">
                                    {log.details}
                                  </pre>
                                </details>
                              ) : null}
                            </article>
                          </li>
                        );
                      })}
                    </ol>
                  </section>
                ))
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
