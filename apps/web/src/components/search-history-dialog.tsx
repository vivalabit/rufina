"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  History,
  LoaderCircle,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { getParserLabel } from "@/features/job-search/formatting";
import {
  fetchSearchHistory,
  fetchSearchReport,
  type SearchHistoryEntry,
  type SearchHistoryFilters,
  type SearchHistoryPage,
} from "@/features/job-search/api/history-client";
import {
  searchDuration,
  searchHistorySummary,
} from "@/features/job-search/model/history";
import { directCompanyCatalog } from "@/lib/direct-company-catalog";
import { cn } from "@/lib/utils";
import { normalizeExternalUrl } from "@/shared/formatting/urls";

const control =
  "h-10 rounded-lg border border-border bg-white px-3 text-sm text-foreground";
const outcomeLabels: Record<string, string> = {
  all: "All results",
  new: "First seen",
  added: "Added to Jobs",
  known: "Already in Jobs",
  duplicate: "Duplicates",
  filtered: "Filtered out",
  uncertain: "Uncertain",
  error: "Errors",
  pending: "Pending",
  missing: "Missing from source",
};

function formatDate(value: string) {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function StatusBadge({ status }: { status: string }) {
  const success = status === "completed";
  const active = status === "running" || status === "queued";
  const Icon = success ? CheckCircle2 : active ? Clock3 : AlertTriangle;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-1 text-xs font-semibold",
        success
          ? "bg-green-50 text-green-800"
          : active
            ? "bg-blue-50 text-blue-800"
            : status === "failed"
              ? "bg-red-50 text-red-800"
              : "bg-amber-50 text-amber-800",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

export function SearchHistoryDialog({
  initialSessionId = null,
  onClose,
  availableJobIds,
  onOpenJob,
}: {
  initialSessionId?: string | null;
  onClose: () => void;
  availableJobIds?: ReadonlySet<string>;
  onOpenJob?: (jobId: string) => void;
}) {
  const [selectedId, setSelectedId] = useState(initialSessionId);
  const [page, setPage] = useState<SearchHistoryPage | null>(null);
  const [report, setReport] = useState<SearchHistoryEntry | null>(null);
  const [offset, setOffset] = useState(0);
  const [period, setPeriod] = useState("");
  const [filters, setFilters] = useState<SearchHistoryFilters>({
    query: "",
    source: "",
    runType: "",
    since: "",
    status: "",
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, []);

  useEffect(() => {
    closeRef.current?.focus();
  }, [selectedId]);

  useEffect(() => {
    const controller = new AbortController();
    let refresh: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    setError("");
    const timer = setTimeout(
      () => {
        const request = selectedId
          ? fetchSearchReport(selectedId, controller.signal).then((value) => {
              if (controller.signal.aborted) return;
              setReport(value);
              if (searchHistorySummary(value).status === "running") {
                refresh = setTimeout(() => setRevision((n) => n + 1), 5000);
              }
            })
          : fetchSearchHistory(offset, filters, controller.signal).then(
              (value) => {
                if (!controller.signal.aborted) setPage(value);
              },
            );
        void request
          .catch((reason: unknown) => {
            if (!controller.signal.aborted)
              setError(
                reason instanceof Error
                  ? reason.message
                  : "Search history could not be loaded",
              );
          })
          .finally(() => {
            if (!controller.signal.aborted) setLoading(false);
          });
      },
      filters.query && !selectedId ? 250 : 0,
    );
    return () => {
      controller.abort();
      clearTimeout(timer);
      clearTimeout(refresh);
    };
  }, [filters, offset, revision, selectedId]);

  function updateFilter(key: keyof SearchHistoryFilters, value: string) {
    setOffset(0);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-2 backdrop-blur-sm sm:p-5"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="search-history-title"
        className="panel flex h-[min(900px,calc(100dvh-40px))] w-full max-w-[1280px] flex-col overflow-hidden border border-border bg-white p-4 shadow-2xl sm:p-6"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            onClose();
          }
          if (event.key !== "Tab") return;
          const focusable = Array.from(
            dialogRef.current?.querySelectorAll<HTMLElement>(
              'button:not(:disabled), a[href], input, select, summary, [tabindex="0"]',
            ) ?? [],
          ).filter((element) => !element.closest("[hidden]"));
          const first = focusable[0];
          const last = focusable.at(-1);
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }}
      >
        <header className="mb-5 flex shrink-0 items-start justify-between gap-4">
          <div>
            {selectedId ? (
              <button
                className="mb-3 inline-flex items-center gap-2 text-sm font-semibold text-accent"
                onClick={() => {
                  setSelectedId(null);
                  setReport(null);
                }}
              >
                <ArrowLeft className="h-4 w-4" />
                Search history
              </button>
            ) : null}
            <h2
              id="search-history-title"
              className="flex items-center gap-2 text-2xl font-bold text-foreground"
            >
              <History className="h-6 w-6 text-accent" />
              {selectedId ? "Search report" : "Search history"}
            </h2>
            {!selectedId && (
              <p className="mt-1 text-sm text-muted">
                Manual and automatic searches, with results from every source.
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              aria-label="Refresh search history"
              title="Refresh"
              className="rounded-lg p-2 text-muted hover:bg-[#fff3e8]"
              onClick={() => setRevision((n) => n + 1)}
            >
              <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            </button>
            <button
              ref={closeRef}
              aria-label="Close search history"
              className="rounded-lg p-2 text-muted hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </header>
        {!selectedId && (
          <div className="mb-4 grid shrink-0 gap-2 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_140px_140px_140px]">
            <label className={cn(control, "flex items-center gap-2")}>
              <Search className="h-4 w-4 shrink-0 text-muted" />
              <input
                aria-label="Search history by name"
                placeholder="Search by name..."
                value={filters.query}
                onChange={(event) => updateFilter("query", event.target.value)}
                className="min-w-0 flex-1 !border-0 !bg-transparent outline-none"
              />
            </label>
            <select
              aria-label="History source"
              className={control}
              value={filters.source}
              onChange={(event) => updateFilter("source", event.target.value)}
            >
              <option value="">All sources</option>
              {[
                "linkedin",
                "indeed",
                "jobs_ch",
                ...directCompanyCatalog.map((company) => company.id),
              ].map((source) => (
                <option key={source} value={source}>
                  {getParserLabel(source)}
                </option>
              ))}
            </select>
            <select
              aria-label="Search trigger"
              className={control}
              value={filters.runType}
              onChange={(event) => updateFilter("runType", event.target.value)}
            >
              <option value="">All searches</option>
              <option value="manual">Manual</option>
              <option value="automatic">Automatic</option>
            </select>
            <select
              aria-label="History period"
              className={control}
              value={period}
              onChange={(event) => {
                setPeriod(event.target.value);
                updateFilter(
                  "since",
                  event.target.value
                    ? new Date(
                        Date.now() - Number(event.target.value) * 86400000,
                      ).toISOString()
                    : "",
                );
              }}
            >
              <option value="">All time</option>
              <option value="1">Last 24 hours</option>
              <option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option>
            </select>
            <select
              aria-label="History status"
              className={control}
              value={filters.status}
              onChange={(event) => updateFilter("status", event.target.value)}
            >
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="partial">Partial</option>
              <option value="failed">Failed</option>
              <option value="running">Running</option>
            </select>
          </div>
        )}
        {error ? (
          <div
            role="alert"
            className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800"
          >
            {error}
            <button
              className="ml-3 font-semibold underline"
              onClick={() => setRevision((n) => n + 1)}
            >
              Try again
            </button>
          </div>
        ) : null}
        <div
          className="job-scroll min-h-0 flex-1 overflow-y-auto"
          aria-busy={loading}
        >
          {loading && (!selectedId || report?.id !== selectedId) ? (
            <div
              role="status"
              className="flex items-center justify-center gap-2 py-16 text-sm text-muted"
            >
              <LoaderCircle className="h-5 w-5 animate-spin" />
              Loading search history...
            </div>
          ) : selectedId ? (
            report?.id === selectedId ? (
              <SearchReport
                key={selectedId}
                entry={report}
                availableJobIds={availableJobIds}
                onOpenJob={onOpenJob}
              />
            ) : null
          ) : page?.items.length ? (
            <div className="grid gap-3">
              {page.items.map((entry) => {
                const summary = searchHistorySummary(entry);
                return (
                  <button
                    key={entry.id}
                    className="group rounded-xl border border-border bg-white p-4 text-left transition hover:border-accent/60 hover:bg-[#fff8f1] sm:p-5"
                    onClick={() => {
                      setReport(null);
                      setSelectedId(entry.id);
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="truncate font-bold text-foreground">
                          {summary.name}
                        </h3>
                        <p className="mt-1 text-xs text-muted">
                          {formatDate(summary.startedAt)} ·{" "}
                          {summary.runType === "automatic"
                            ? "Automatic"
                            : "Manual"}{" "}
                          · {searchDuration(summary.duration)}
                        </p>
                      </div>
                      <StatusBadge status={summary.status} />
                    </div>
                    <p className="mt-3 line-clamp-2 text-sm text-muted">
                      {summary.sources.map(getParserLabel).join(" · ")}
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                      <span>
                        <b>{summary.found}</b> found
                      </span>
                      <span>
                        <b>{summary.firstSeen}</b> first seen
                      </span>
                      <span className="text-green-800">
                        <b>{summary.added}</b> added
                      </span>
                      <span>
                        <b>{summary.filtered}</b> rejected
                      </span>
                      <span className="ml-auto inline-flex items-center gap-1 font-semibold text-accent">
                        View report
                        <ArrowRight className="h-4 w-4" />
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : !error ? (
            <div className="py-20 text-center">
              <History className="mx-auto mb-3 h-8 w-8 text-muted" />
              <h3 className="font-bold">No searches found</h3>
              <p className="mt-2 text-sm text-muted">
                Run a vacancy search or adjust the history filters.
              </p>
            </div>
          ) : null}
        </div>
        <footer className="mt-4 flex shrink-0 items-center justify-between border-t border-border pt-4">
          {!selectedId ? (
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                className={control}
                disabled={offset === 0 || loading}
                onClick={() => setOffset(Math.max(0, offset - 25))}
              >
                Previous
              </Button>
              <span className="text-xs text-muted">
                Page {Math.floor(offset / 25) + 1}
              </span>
              <Button
                variant="ghost"
                className={control}
                disabled={page?.nextOffset == null || loading}
                onClick={() => setOffset(page?.nextOffset ?? 0)}
              >
                Next
              </Button>
            </div>
          ) : (
            <span className="text-xs text-muted">
              Settings and results are saved at the time of each search.
            </span>
          )}
          <Button variant="ghost" className={control} onClick={onClose}>
            Close
          </Button>
        </footer>
      </div>
    </div>
  );
}

function SearchReport({
  entry,
  availableJobIds,
  onOpenJob,
}: {
  entry: SearchHistoryEntry;
  availableJobIds?: ReadonlySet<string>;
  onOpenJob?: (jobId: string) => void;
}) {
  const [tab, setTab] = useState("sources");
  const [sourceFilter, setSourceFilter] = useState("");
  const [outcome, setOutcome] = useState("all");
  const [vacancyPage, setVacancyPage] = useState(0);
  const tabListRef = useRef<HTMLDivElement>(null);
  const summary = searchHistorySummary(entry);
  const sources = entry.runs.flatMap((run) =>
    (run.report?.sources ?? []).map((source) => ({ ...source, runId: run.id })),
  );
  const vacancies = entry.runs.flatMap((run) =>
    (run.report?.vacancies ?? []).map((vacancy, index) => ({
      ...vacancy,
      key: `${run.id}:${index}`,
    })),
  );
  const legacy = entry.runs.some((run) => !run.reportVersion);
  const detailsRemoved = entry.runs.some((run) => run.report?.detailsRemoved);
  const reportsReady = entry.runs.every((run) => run.report);
  const fullCatalogSources = sources.filter(
    (source) => source.missing !== null,
  );
  const filteredVacancies = vacancies.filter(
    (vacancy) =>
      (!sourceFilter || vacancy.source === sourceFilter) &&
      (outcome === "all" ||
        (outcome === "new"
          ? vacancy.discovery === "new"
          : vacancy.outcome === outcome)),
  );
  const notices = [
    ...new Set(
      entry.runs.flatMap((run) => [
        ...(run.warning ? [run.warning] : []),
        ...Object.entries(run.sourceErrors).map(
          ([source, error]) => `${getParserLabel(source)}: ${error}`,
        ),
        ...(run.report?.sources.flatMap((source) =>
          source.warnings.map(
            (warning) => `${getParserLabel(source.source)}: ${warning}`,
          ),
        ) ?? []),
      ]),
    ),
  ];
  function inspect(source: string, filter: string) {
    setSourceFilter(source);
    setOutcome(filter);
    setVacancyPage(0);
    setTab("vacancies");
    requestAnimationFrame(() =>
      tabListRef.current
        ?.querySelector<HTMLButtonElement>("#report-tab-vacancies")
        ?.focus(),
    );
  }

  return (
    <>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-xl font-bold sm:text-2xl">{summary.name}</h3>
          <p className="mt-2 text-sm text-muted">
            {formatDate(summary.startedAt)} ·{" "}
            {summary.runType === "automatic"
              ? "Automatic search"
              : "Manual search"}{" "}
            · {searchDuration(summary.duration)}
          </p>
        </div>
        <StatusBadge status={summary.status} />
      </div>
      {legacy && (
        <p className="mb-4 rounded-lg bg-[#fff8f1] p-3 text-sm text-muted">
          Detailed source and vacancy results were not collected for older
          searches. Their saved summary and settings are still available.
        </p>
      )}
      {detailsRemoved && (
        <p className="mb-4 rounded-lg bg-[#fff8f1] p-3 text-sm text-muted">
          Vacancy decisions were removed under your AI data privacy settings.
          Search totals are retained.
        </p>
      )}
      {!legacy && !reportsReady && (
        <p className="mb-4 rounded-lg bg-[#fff8f1] p-3 text-sm text-muted">
          {summary.status === "running"
            ? "Source results will appear when parsing finishes. This report refreshes automatically."
            : "This search stopped before detailed source results could be saved. See the errors below."}
        </p>
      )}
      <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {[
          {
            label: reportsReady ? "Received" : "Found",
            value: reportsReady
              ? sources.reduce((n, source) => n + (source.received ?? 0), 0)
              : summary.found,
            filter: "all",
          },
          { label: "First seen", value: summary.firstSeen, filter: "new" },
          { label: "Added to Jobs", value: summary.added, filter: "added" },
          {
            label: "Filtered out",
            value: reportsReady
              ? sources.reduce((n, source) => n + source.filtered, 0)
              : summary.filtered,
            filter: "filtered",
          },
          {
            label: "Missing from source",
            value: fullCatalogSources.length
              ? fullCatalogSources.reduce(
                  (n, source) => n + (source.missing ?? 0),
                  0,
                )
              : "—",
            filter: "missing",
          },
        ].map((stat) => (
          <button
            key={stat.label}
            disabled={!reportsReady || detailsRemoved || stat.value === "—"}
            onClick={() => inspect("", stat.filter)}
            className="rounded-lg border border-border p-4 text-left enabled:hover:border-accent/70 enabled:hover:bg-[#fff8f1]"
          >
            <span className="block text-2xl font-bold">{stat.value}</span>
            <span className="mt-1 block text-xs text-muted">{stat.label}</span>
          </button>
        ))}
      </div>
      <div
        ref={tabListRef}
        role="tablist"
        aria-label="Report sections"
        className="mb-4 flex gap-5 border-b border-border"
        onKeyDown={(event) => {
          const tabs = ["sources", "vacancies", "settings"];
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
            return;
          event.preventDefault();
          const index =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? 2
                : (tabs.indexOf(tab) + (event.key === "ArrowRight" ? 1 : 2)) %
                  tabs.length;
          setTab(tabs[index]);
          tabListRef.current
            ?.querySelector<HTMLButtonElement>(`#report-tab-${tabs[index]}`)
            ?.focus();
        }}
      >
        {["sources", "vacancies", "settings"].map((name) => (
          <button
            key={name}
            role="tab"
            tabIndex={tab === name ? 0 : -1}
            id={`report-tab-${name}`}
            aria-controls={`report-panel-${name}`}
            aria-selected={tab === name}
            className={cn(
              "border-b-2 px-2 py-3 text-sm font-semibold",
              tab === name
                ? "border-accent text-accent"
                : "border-transparent text-muted",
            )}
            onClick={() => setTab(name)}
          >
            {name === "settings"
              ? "Search settings"
              : name.charAt(0).toUpperCase() + name.slice(1)}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`report-panel-${tab}`}
        aria-labelledby={`report-tab-${tab}`}
      >
        {tab === "sources" && (
          <>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-left text-sm">
                <thead className="bg-[#faf8f6] text-xs text-muted">
                  <tr>
                    {[
                      "Source",
                      "Received",
                      "First seen",
                      "Added",
                      "Filtered",
                      "Missing",
                      "Status",
                    ].map((label) => (
                      <th
                        className="whitespace-nowrap px-3 py-3 font-semibold"
                        key={label}
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sources.map((source) => (
                    <tr
                      key={`${source.runId}:${source.source}`}
                      className="border-t border-border align-top"
                    >
                      <td className="min-w-[185px] px-3 py-3">
                        <span className="font-semibold">
                          {getParserLabel(source.source)}
                        </span>
                        <span className="mt-1 block text-xs text-muted">
                          {searchDuration(source.durationSeconds)}
                          {source.attempts != null
                            ? ` · ${source.attempts} attempt${source.attempts === 1 ? "" : "s"}`
                            : ""}
                        </span>
                        <details className="mt-2 text-xs">
                          <summary className="cursor-pointer text-muted">
                            More details
                          </summary>
                          <div className="mt-2 grid gap-1.5">
                            {[
                              "known",
                              "duplicate",
                              "uncertain",
                              "error",
                              "pending",
                            ].map((key) => (
                              <button
                                key={key}
                                className="text-left text-accent"
                                onClick={() => inspect(source.source, key)}
                              >
                                {outcomeLabels[key]}: {source[key as "known"]}
                              </button>
                            ))}
                            <span>Updated: {source.updated}</span>
                            <span>Unchanged: {source.observed}</span>
                            <span>
                              {source.fullCatalog
                                ? "Complete company catalog"
                                : "Search results; missing vacancies cannot be inferred"}
                            </span>
                          </div>
                        </details>
                      </td>
                      {[
                        { value: source.received, filter: "all" },
                        { value: source.firstSeen, filter: "new" },
                        { value: source.added, filter: "added" },
                        { value: source.filtered, filter: "filtered" },
                        { value: source.missing, filter: "missing" },
                      ].map((cell) => (
                        <td key={cell.filter} className="px-3 py-3">
                          {cell.value == null || source.received == null ? (
                            <span className="text-muted">—</span>
                          ) : (
                            <button
                              aria-label={`${getParserLabel(source.source)}: ${outcomeLabels[cell.filter]} ${cell.value}`}
                              onClick={() =>
                                inspect(source.source, cell.filter)
                              }
                              className="rounded px-1 font-medium underline decoration-border underline-offset-4 hover:text-accent"
                            >
                              {cell.value}
                            </button>
                          )}
                        </td>
                      ))}
                      <td className="px-3 py-3">
                        <StatusBadge status={source.status} />
                        {source.fullCatalog && (
                          <span className="mt-2 block text-xs text-muted">
                            Full catalog scan
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!sources.length &&
                    entry.runs.flatMap((run) =>
                      run.sources.map((source) => (
                        <tr
                          key={`${run.id}:${source}`}
                          className="border-t border-border"
                        >
                          <td className="px-3 py-3 font-semibold">
                            {getParserLabel(source)}
                          </td>
                          <td colSpan={5} className="px-3 py-3 text-muted">
                            Detailed counts unavailable
                          </td>
                          <td className="px-3 py-3">
                            <StatusBadge
                              status={
                                run.sourceErrors[source] ? "failed" : "unknown"
                              }
                            />
                          </td>
                        </tr>
                      )),
                    )}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs leading-5 text-muted">
              Received counts records returned by each parser, including
              duplicates. First seen and Added are subsets, not additional
              totals. Missing is checked only against previously tracked
              vacancies after a successful complete company catalog scan.
            </p>
          </>
        )}
        {tab === "vacancies" && (
          <>
            <div className="mb-3 flex flex-wrap gap-2">
              <select
                aria-label="Report vacancy source"
                className={control}
                value={sourceFilter}
                onChange={(event) => {
                  setSourceFilter(event.target.value);
                  setVacancyPage(0);
                }}
              >
                <option value="">All sources</option>
                {summary.sources.map((source) => (
                  <option key={source} value={source}>
                    {getParserLabel(source)}
                  </option>
                ))}
              </select>
              <select
                aria-label="Vacancy outcome"
                className={control}
                value={outcome}
                onChange={(event) => {
                  setOutcome(event.target.value);
                  setVacancyPage(0);
                }}
              >
                {Object.entries(outcomeLabels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
              <span className="self-center text-sm text-muted">
                {filteredVacancies.length} results
              </span>
            </div>
            <div className="grid gap-2">
              {filteredVacancies
                .slice(vacancyPage * 50, (vacancyPage + 1) * 50)
                .map((vacancy) => {
                  const href = normalizeExternalUrl(vacancy.url);
                  return (
                    <article
                      key={vacancy.key}
                      className="rounded-lg border border-border p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          {href ? (
                            <a
                              className="font-semibold hover:text-accent hover:underline"
                              href={href}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {vacancy.title}
                            </a>
                          ) : (
                            <span className="font-semibold">
                              {vacancy.title}
                            </span>
                          )}
                          <p className="mt-1 text-xs text-muted">
                            {vacancy.company} · {getParserLabel(vacancy.source)}
                            {vacancy.discovery === "new"
                              ? " · First seen"
                              : vacancy.discovery === "updated"
                                ? " · Updated"
                                : ""}
                          </p>
                        </div>
                        <span className="whitespace-nowrap rounded-md bg-[#fff8f1] px-2 py-1 text-xs font-semibold">
                          {outcomeLabels[vacancy.outcome]}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-muted">
                        {vacancy.reason || "Waiting for processing."}
                      </p>
                      {vacancy.jobId &&
                        availableJobIds?.has(vacancy.jobId) &&
                        onOpenJob && (
                          <button
                            className="mt-2 text-sm font-semibold text-accent"
                            onClick={() => onOpenJob(vacancy.jobId!)}
                          >
                            Open in Jobs
                          </button>
                        )}
                    </article>
                  );
                })}
            </div>
            {!filteredVacancies.length && (
              <p className="py-10 text-center text-sm text-muted">
                {legacy
                  ? "Vacancy details were not collected for this search."
                  : "No vacancies match this selection."}
              </p>
            )}
            {filteredVacancies.length > 50 && (
              <div className="mt-3 flex items-center gap-3">
                <Button
                  variant="ghost"
                  disabled={!vacancyPage}
                  onClick={() => setVacancyPage((n) => n - 1)}
                >
                  Previous
                </Button>
                <span className="text-xs text-muted">
                  Page {vacancyPage + 1}
                </span>
                <Button
                  variant="ghost"
                  disabled={(vacancyPage + 1) * 50 >= filteredVacancies.length}
                  onClick={() => setVacancyPage((n) => n + 1)}
                >
                  Next
                </Button>
              </div>
            )}
          </>
        )}
        {tab === "settings" && (
          <div className="grid gap-4">
            {entry.runs.map((run) => (
              <section
                key={run.id}
                className="rounded-lg border border-border p-4"
              >
                <h4 className="mb-3 font-semibold">
                  {run.sources.map(getParserLabel).join(" · ")}
                </h4>
                <SettingsSnapshot
                  value={
                    run.configSnapshot ?? { message: "Settings unavailable" }
                  }
                />
              </section>
            ))}
          </div>
        )}
      </div>
      {notices.length > 0 && (
        <div className="mt-5 grid gap-2">
          {notices.map((notice) => (
            <p
              key={notice}
              className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50 p-3 text-sm text-amber-900"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="min-w-0 break-words">{notice}</span>
            </p>
          ))}
        </div>
      )}
    </>
  );
}

function SettingsSnapshot({ value }: { value: Record<string, unknown> }) {
  return (
    <dl className="grid gap-2 text-sm">
      {Object.entries(value)
        .filter(
          ([key]) =>
            !["id", "createdAt", "updatedAt", "schemaVersion"].includes(key),
        )
        .map(([key, item]) => {
          if (item == null) return null;
          const label = key
            .replace(/([A-Z])/g, " $1")
            .replace(/^./, (letter) => letter.toUpperCase());
          return (
            <div key={key} className="rounded-md bg-[#faf8f6] p-2.5">
              <dt className="text-xs font-semibold text-muted">{label}</dt>
              <dd className="mt-1 break-words">
                {typeof item === "object" && !Array.isArray(item) ? (
                  <SettingsSnapshot value={item as Record<string, unknown>} />
                ) : Array.isArray(item) ? (
                  item.length ? (
                    <div className="flex flex-wrap gap-2">
                      {item.map((part, index) =>
                        part && typeof part === "object" ? (
                          <SettingsSnapshot
                            key={index}
                            value={part as Record<string, unknown>}
                          />
                        ) : (
                          <span
                            key={index}
                            className="rounded bg-white px-2 py-1"
                          >
                            {String(part)}
                          </span>
                        ),
                      )}
                    </div>
                  ) : (
                    "None"
                  )
                ) : typeof item === "boolean" ? (
                  item ? (
                    "Enabled"
                  ) : (
                    "Disabled"
                  )
                ) : (
                  String(item) || "Any"
                )}
              </dd>
            </div>
          );
        })}
    </dl>
  );
}
