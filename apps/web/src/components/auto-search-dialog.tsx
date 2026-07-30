"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  CalendarClock,
  Check,
  Copy,
  Edit3,
  ExternalLink,
  LoaderCircle,
  Play,
  Plus,
  Power,
  RotateCcw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const sourceOptions = [
  { id: "linkedin", label: "LinkedIn" },
  { id: "indeed", label: "Indeed" },
  { id: "jobs_ch", label: "jobs.ch" },
] as const;
const weekdayOptions = [
  { id: 0, short: "Mon", label: "Monday" },
  { id: 1, short: "Tue", label: "Tuesday" },
  { id: 2, short: "Wed", label: "Wednesday" },
  { id: 3, short: "Thu", label: "Thursday" },
  { id: 4, short: "Fri", label: "Friday" },
  { id: 5, short: "Sat", label: "Saturday" },
  { id: 6, short: "Sun", label: "Sunday" },
] as const;
const timezoneSuggestions = [
  "Europe/Zurich",
  "Europe/Berlin",
  "Europe/London",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Singapore",
  "UTC",
];
const seniorityOptions = [
  { id: "intern", label: "Intern" },
  { id: "entry", label: "Entry" },
  { id: "junior", label: "Junior" },
  { id: "associate", label: "Associate" },
  { id: "mid", label: "Mid" },
  { id: "senior", label: "Senior" },
  { id: "lead", label: "Lead" },
  { id: "director", label: "Director" },
  { id: "executive", label: "Executive" },
] as const;
const screeningFieldOptions = [
  ["title", "Title"],
  ["company", "Company"],
  ["location", "Location"],
  ["description", "Description"],
  ["employmentType", "Employment type"],
  ["seniority", "Seniority"],
  ["salaryMin", "Minimum salary"],
  ["salaryMax", "Maximum salary"],
  ["postedAt", "Posted at"],
  ["source", "Source"],
] as const;
const screeningOperatorOptions = [
  ["equals", "equals"],
  ["notEquals", "does not equal"],
  ["contains", "contains"],
  ["notContains", "does not contain"],
  ["startsWith", "starts with"],
  ["endsWith", "ends with"],
  ["greaterThan", "is greater than"],
  ["greaterThanOrEqual", "is at least"],
  ["lessThan", "is less than"],
  ["lessThanOrEqual", "is at most"],
  ["in", "is one of"],
  ["notIn", "is not one of"],
  ["matches", "matches regex"],
] as const;

type JobSearchSource = (typeof sourceOptions)[number]["id"];
type JobSearchFrequency = "daily" | "weekdays" | "selected_days";
type ScreeningSeniority = (typeof seniorityOptions)[number]["id"];

type ScreeningHardRuleDraft = {
  id: string;
  field: string;
  operator: string;
  value: string;
  enabled: boolean;
  original: Record<string, unknown>;
};

export type JobSearchConfig = {
  id: string;
  name: string;
  filters: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type JobSearchSchedule = {
  id: string;
  name: string;
  configId: string;
  sources: JobSearchSource[];
  frequency: JobSearchFrequency;
  weekdays: number[];
  localTime: string;
  timezone: string;
  aiAnalysisEnabled: boolean;
  enabled: boolean;
  nextRunAt: string | null;
  lastRunAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type JobScreeningAuditEntry = {
  id: string;
  jobId: string;
  decision: "keep" | "reject" | "uncertain";
  reasonCode: string;
  reason: string;
  matchedRuleIds: string[];
  configHash: string;
  configId: string | null;
  model: string;
  promptVersion: string;
  title: string;
  company: string;
  sourceUrl: string;
  checkedAt: string;
  invalidatedAt: string | null;
  manuallyAllowedAt: string | null;
  canRecheck: boolean;
  canAllowManually: boolean;
};

type AutoSearchDialogProps = {
  open: boolean;
  onClose: () => void;
  onVacanciesChanged?: () => void | Promise<void>;
};

type EditorMode = "create" | "edit" | "duplicate";

type ScheduleDraft = {
  id: string;
  mode: EditorMode;
  name: string;
  sources: JobSearchSource[];
  configId: string;
  createConfig: boolean;
  configName: string;
  keywords: string;
  location: string;
  frequency: JobSearchFrequency;
  weekdays: number[];
  localTime: string;
  timezone: string;
  resultsLimit: string;
  deduplicate: boolean;
  screeningTouched: boolean;
  screeningEnabled: boolean;
  targetRoles: string;
  excludedRoles: string;
  allowedSeniority: ScreeningSeniority[];
  excludedSeniority: ScreeningSeniority[];
  hardRules: ScreeningHardRuleDraft[];
  aiAnalysisEnabled: boolean;
  enabled: boolean;
};

function defaultDraft(): ScheduleDraft {
  return {
    id: "",
    mode: "create",
    name: "",
    sources: ["linkedin"],
    configId: "",
    createConfig: true,
    configName: "",
    keywords: "",
    location: "",
    frequency: "weekdays",
    weekdays: [0, 1, 2, 3, 4],
    localTime: "09:00",
    timezone: localTimezone(),
    resultsLimit: "50",
    deduplicate: true,
    screeningTouched: false,
    screeningEnabled: false,
    targetRoles: "",
    excludedRoles: "",
    allowedSeniority: [],
    excludedSeniority: [],
    hardRules: [],
    aiAnalysisEnabled: true,
    enabled: true,
  };
}

export function AutoSearchDialog({
  open,
  onClose,
  onVacanciesChanged,
}: AutoSearchDialogProps) {
  const [view, setView] = useState<"list" | "form" | "audit">("list");
  const [configs, setConfigs] = useState<JobSearchConfig[]>([]);
  const [schedules, setSchedules] = useState<JobSearchSchedule[]>([]);
  const [auditEntries, setAuditEntries] = useState<JobScreeningAuditEntry[]>([]);
  const [draft, setDraft] = useState<ScheduleDraft>(defaultDraft);
  const [status, setStatus] = useState<"idle" | "loading" | "saving" | "error">(
    "idle",
  );
  const [message, setMessage] = useState("");
  const [runningScheduleId, setRunningScheduleId] = useState("");
  const [busyScheduleId, setBusyScheduleId] = useState("");
  const [auditLoading, setAuditLoading] = useState(false);
  const [busyAuditId, setBusyAuditId] = useState("");

  const configById = useMemo(
    () => new Map(configs.map((config) => [config.id, config])),
    [configs],
  );

  useEffect(() => {
    if (!open) return;
    setView("list");
    setMessage("");
    void loadSearchData();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (view !== "list") {
        setView("list");
        setMessage("");
      } else {
        onClose();
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open, view]);

  if (!open) return null;

  async function loadSearchData() {
    setStatus("loading");
    try {
      const [nextConfigs, nextSchedules] = await Promise.all([
        requestJson<JobSearchConfig[]>("/job-search/configs"),
        requestJson<JobSearchSchedule[]>("/job-search/schedules"),
      ]);
      setConfigs(nextConfigs);
      setSchedules(nextSchedules);
      setStatus("idle");
    } catch (error) {
      setStatus("error");
      setMessage(errorMessage(error));
    }
  }

  async function openAudit() {
    setView("audit");
    setMessage("");
    setAuditLoading(true);
    try {
      setAuditEntries(
        await requestJson<JobScreeningAuditEntry[]>(
          "/job-search/screening-audit?limit=200",
        ),
      );
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setAuditLoading(false);
    }
  }

  async function runAuditAction(
    entry: JobScreeningAuditEntry,
    action: "recheck" | "allow",
  ) {
    if (
      action === "allow" &&
      !window.confirm(`Allow “${entry.title || entry.jobId}” manually?`)
    ) {
      return;
    }
    setBusyAuditId(entry.id);
    setMessage("");
    try {
      const updated = await requestJson<JobScreeningAuditEntry>(
        `/job-search/screening-audit/${encodeURIComponent(entry.id)}/${action}`,
        { method: "POST" },
      );
      setAuditEntries((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      let refreshFailed = false;
      try {
        await onVacanciesChanged?.();
      } catch {
        refreshFailed = true;
      }
      await openAudit();
      setMessage(
        [
          action === "allow"
            ? "Vacancy allowed manually and added to the client list"
            : `Screening completed: ${updated.decision}`,
          refreshFailed ? "Vacancies could not be refreshed" : "",
        ]
          .filter(Boolean)
          .join(" · "),
      );
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusyAuditId("");
    }
  }

  function openCreate() {
    const next = defaultDraft();
    if (configs.length > 0) {
      applyConfigToDraft(next, configs[0]);
      next.createConfig = false;
    }
    setDraft(next);
    setMessage("");
    setView("form");
  }

  function openEdit(schedule: JobSearchSchedule) {
    const config = configById.get(schedule.configId);
    setDraft(draftFromSchedule(schedule, config, "edit"));
    setMessage("");
    setView("form");
  }

  function openDuplicate(schedule: JobSearchSchedule) {
    const config = configById.get(schedule.configId);
    setDraft({
      ...draftFromSchedule(schedule, config, "duplicate"),
      id: "",
      name: `${schedule.name} copy`,
      enabled: true,
    });
    setMessage("");
    setView("form");
  }

  async function saveRule() {
    const validation = validateDraft(draft);
    if (validation) {
      setStatus("error");
      setMessage(validation);
      return;
    }

    setStatus("saving");
    setMessage("");
    try {
      const configId = await saveConfigForDraft(draft, configById);
      const schedulePayload = {
        name: draft.name.trim(),
        configId,
        sources: draft.sources,
        frequency: draft.frequency,
        weekdays:
          draft.frequency === "selected_days" ? draft.weekdays : [],
        localTime: withSeconds(draft.localTime),
        timezone: draft.timezone.trim(),
        aiAnalysisEnabled: draft.aiAnalysisEnabled,
        enabled: draft.enabled,
      };
      if (draft.mode === "edit" && draft.id) {
        await requestJson<JobSearchSchedule>(
          `/job-search/schedules/${encodeURIComponent(draft.id)}`,
          {
            method: "PATCH",
            headers: jsonHeaders,
            body: JSON.stringify(schedulePayload),
          },
        );
      } else {
        await requestJson<JobSearchSchedule>("/job-search/schedules", {
          method: "POST",
          headers: jsonHeaders,
          body: JSON.stringify(schedulePayload),
        });
      }
      setView("list");
      setMessage(
        draft.mode === "edit"
          ? "Auto-search updated"
          : draft.mode === "duplicate"
            ? "Auto-search duplicated"
            : "Auto-search created",
      );
      await loadSearchData();
    } catch (error) {
      setStatus("error");
      setMessage(errorMessage(error));
    }
  }

  async function toggleEnabled(schedule: JobSearchSchedule) {
    setBusyScheduleId(schedule.id);
    setMessage("");
    try {
      const updated = await requestJson<JobSearchSchedule>(
        `/job-search/schedules/${encodeURIComponent(schedule.id)}`,
        {
          method: "PATCH",
          headers: jsonHeaders,
          body: JSON.stringify({ enabled: !schedule.enabled }),
        },
      );
      setSchedules((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusyScheduleId("");
    }
  }

  async function runNow(schedule: JobSearchSchedule) {
    setRunningScheduleId(schedule.id);
    setMessage("");
    try {
      const run = await requestJson<{
        status: string;
        jobsFound: number;
        jobsAdded: number;
        warning?: string | null;
      }>(`/job-search/schedules/${encodeURIComponent(schedule.id)}/run`, {
        method: "POST",
      });
      const parts = [
        `${schedule.name}: ${run.status}`,
        `${run.jobsFound} found`,
        `${run.jobsAdded} added`,
        run.warning,
      ].filter(Boolean);
      try {
        await onVacanciesChanged?.();
      } catch {
        parts.push("Vacancies could not be refreshed");
      }
      setMessage(parts.join(" · "));
      await loadSearchData();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setRunningScheduleId("");
    }
  }

  async function deleteRule(schedule: JobSearchSchedule) {
    if (!window.confirm(`Delete auto-search “${schedule.name}”?`)) return;
    setBusyScheduleId(schedule.id);
    setMessage("");
    try {
      await requestJson<void>(
        `/job-search/schedules/${encodeURIComponent(schedule.id)}`,
        { method: "DELETE" },
      );
      setSchedules((current) =>
        current.filter((item) => item.id !== schedule.id),
      );
      setMessage("Auto-search deleted");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusyScheduleId("");
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-3 backdrop-blur-sm sm:p-5"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="auto-search-dialog-title"
        className="panel flex max-h-[calc(100vh-24px)] w-full max-w-[1040px] flex-col overflow-hidden border-white/[0.11] bg-[#101720]/98 shadow-[0_28px_90px_rgba(0,0,0,0.62)] sm:max-h-[calc(100vh-40px)]"
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-4 py-4 sm:px-6">
          <div className="flex min-w-0 items-start gap-3">
            {view !== "list" ? (
              <button
                type="button"
                aria-label="Back to auto-searches"
                onClick={() => {
                  setView("list");
                  setMessage("");
                }}
                className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border text-muted transition hover:bg-white/[0.06] hover:text-white"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
            ) : (
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-violet-500/15 text-violet-300">
                <CalendarClock className="h-5 w-5" />
              </div>
            )}
            <div className="min-w-0">
              <h2
                id="auto-search-dialog-title"
                className="truncate text-xl font-bold text-white sm:text-2xl"
              >
                {view === "list"
                  ? "Automatic searches"
                  : view === "audit"
                    ? "Screening audit"
                    : draft.mode === "edit"
                      ? "Edit auto-search"
                      : draft.mode === "duplicate"
                        ? "Duplicate auto-search"
                        : "New auto-search"}
              </h2>
              <p className="mt-1 text-xs font-medium text-muted sm:text-sm">
                {view === "list"
                  ? "Run vacancy searches on your schedule."
                  : view === "audit"
                    ? "Internal screening decisions are kept separate from the vacancy list."
                    : "Each rule has one local run time. Duplicate it to add another time."}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close automatic searches"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        {view === "list" ? (
          <AutoSearchList
            configs={configById}
            schedules={schedules}
            loading={status === "loading"}
            runningScheduleId={runningScheduleId}
            busyScheduleId={busyScheduleId}
            onCreate={openCreate}
            onEdit={openEdit}
            onDuplicate={openDuplicate}
            onRunNow={(schedule) => void runNow(schedule)}
            onDelete={(schedule) => void deleteRule(schedule)}
            onToggleEnabled={(schedule) => void toggleEnabled(schedule)}
            onOpenAudit={() => void openAudit()}
          />
        ) : view === "form" ? (
          <AutoSearchForm
            draft={draft}
            configs={configs}
            saving={status === "saving"}
            onChange={setDraft}
            onCancel={() => {
              setView("list");
              setMessage("");
            }}
            onSave={() => void saveRule()}
          />
        ) : (
          <ScreeningAudit
            entries={auditEntries}
            loading={auditLoading}
            busyId={busyAuditId}
            onRecheck={(entry) => void runAuditAction(entry, "recheck")}
            onAllow={(entry) => void runAuditAction(entry, "allow")}
          />
        )}

        {message ? (
          <div
            role={status === "error" ? "alert" : "status"}
            className={cn(
              "shrink-0 border-t border-border px-4 py-2.5 text-xs font-semibold sm:px-6",
              status === "error"
                ? "bg-red-500/8 text-red-200"
                : "bg-white/[0.025] text-[#cbd3df]",
            )}
          >
            {message}
          </div>
        ) : null}
      </section>
    </div>
  );
}

function AutoSearchList({
  configs,
  schedules,
  loading,
  runningScheduleId,
  busyScheduleId,
  onCreate,
  onEdit,
  onDuplicate,
  onRunNow,
  onDelete,
  onToggleEnabled,
  onOpenAudit,
}: {
  configs: Map<string, JobSearchConfig>;
  schedules: JobSearchSchedule[];
  loading: boolean;
  runningScheduleId: string;
  busyScheduleId: string;
  onCreate: () => void;
  onEdit: (schedule: JobSearchSchedule) => void;
  onDuplicate: (schedule: JobSearchSchedule) => void;
  onRunNow: (schedule: JobSearchSchedule) => void;
  onDelete: (schedule: JobSearchSchedule) => void;
  onToggleEnabled: (schedule: JobSearchSchedule) => void;
  onOpenAudit: () => void;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <p className="text-xs font-semibold text-muted">
          {schedules.length} {schedules.length === 1 ? "rule" : "rules"}
        </p>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={onOpenAudit}>
            <ShieldCheck className="h-4 w-4" />
            Screening audit
          </Button>
          <Button size="sm" onClick={onCreate}>
            <Plus className="h-4 w-4" />
            New auto-search
          </Button>
        </div>
      </div>

      <div className="job-scroll min-h-0 flex-1 overflow-y-auto px-4 pb-5 sm:px-6">
        {loading ? (
          <div className="grid min-h-[280px] place-items-center text-muted">
            <LoaderCircle className="h-6 w-6 animate-spin" />
          </div>
        ) : schedules.length === 0 ? (
          <div className="grid min-h-[300px] place-items-center rounded-xl border border-dashed border-border bg-white/[0.018] p-6 text-center">
            <div>
              <CalendarClock className="mx-auto h-9 w-9 text-muted" />
              <h3 className="mt-3 text-lg font-bold text-white">
                No automatic searches yet
              </h3>
              <p className="mt-1 max-w-md text-sm text-muted">
                Create a rule for each source and local run time you need.
              </p>
              <Button className="mt-5" onClick={onCreate}>
                <Plus className="h-4 w-4" />
                Create first rule
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid gap-3">
            {schedules.map((schedule) => {
              const config = configs.get(schedule.configId);
              const isRunning = runningScheduleId === schedule.id;
              const isBusy = busyScheduleId === schedule.id;
              return (
                <article
                  key={schedule.id}
                  className="rounded-xl border border-border bg-white/[0.025] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]"
                >
                  <div className="grid gap-4 xl:grid-cols-[minmax(180px,1.2fr)_minmax(130px,.8fr)_minmax(150px,1fr)_minmax(170px,1fr)_minmax(165px,1fr)_auto] xl:items-center">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            "h-2 w-2 shrink-0 rounded-full",
                            schedule.enabled
                              ? "bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.7)]"
                              : "bg-slate-500",
                          )}
                        />
                        <h3 className="truncate text-sm font-bold text-white">
                          {schedule.name}
                        </h3>
                      </div>
                      <p className="mt-1 text-[11px] text-muted">
                        {schedule.enabled ? "Enabled" : "Paused"}
                      </p>
                    </div>
                    <ListField label="Sources">
                      <div className="flex flex-wrap gap-1">
                        {schedule.sources.map((source) => (
                          <span
                            key={source}
                            className="rounded-md border border-white/[0.08] bg-white/[0.035] px-2 py-1 text-[10px] font-bold text-[#d9e0ea]"
                          >
                            {sourceLabel(source)}
                          </span>
                        ))}
                      </div>
                    </ListField>
                    <ListField label="Config">
                      <span className="line-clamp-2 text-xs font-semibold text-[#d9e0ea]">
                        {config?.name ?? "Missing config"}
                      </span>
                      {config ? (
                        <span className="mt-0.5 block line-clamp-2 text-[10px] leading-4 text-muted">
                          {screeningSummary(config.filters)}
                        </span>
                      ) : null}
                    </ListField>
                    <ListField label="Schedule">
                      <span className="text-xs font-semibold text-[#d9e0ea]">
                        {scheduleLabel(schedule)}
                      </span>
                      <span className="mt-0.5 block text-[10px] text-muted">
                        {schedule.timezone}
                      </span>
                    </ListField>
                    <ListField label="Next run">
                      <span className="text-xs font-semibold text-[#d9e0ea]">
                        {formatNextRun(schedule)}
                      </span>
                    </ListField>
                    <div className="flex flex-wrap items-center gap-1.5 xl:justify-end">
                      <IconAction
                        label={`${schedule.enabled ? "Disable" : "Enable"} ${schedule.name}`}
                        disabled={isBusy}
                        onClick={() => onToggleEnabled(schedule)}
                      >
                        <Power className="h-3.5 w-3.5" />
                      </IconAction>
                      <IconAction
                        label={`Edit ${schedule.name}`}
                        onClick={() => onEdit(schedule)}
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                      </IconAction>
                      <IconAction
                        label={`Duplicate ${schedule.name}`}
                        onClick={() => onDuplicate(schedule)}
                      >
                        <Copy className="h-3.5 w-3.5" />
                      </IconAction>
                      <IconAction
                        label={`Run ${schedule.name} now`}
                        disabled={isRunning}
                        onClick={() => onRunNow(schedule)}
                      >
                        {isRunning ? (
                          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Play className="h-3.5 w-3.5" />
                        )}
                      </IconAction>
                      <IconAction
                        label={`Delete ${schedule.name}`}
                        danger
                        disabled={isBusy}
                        onClick={() => onDelete(schedule)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </IconAction>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function ScreeningAudit({
  entries,
  loading,
  busyId,
  onRecheck,
  onAllow,
}: {
  entries: JobScreeningAuditEntry[];
  loading: boolean;
  busyId: string;
  onRecheck: (entry: JobScreeningAuditEntry) => void;
  onAllow: (entry: JobScreeningAuditEntry) => void;
}) {
  if (loading) {
    return (
      <div className="grid min-h-[320px] flex-1 place-items-center text-muted">
        <LoaderCircle className="h-6 w-6 animate-spin" />
      </div>
    );
  }
  return (
    <div className="job-scroll min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
      {entries.length === 0 ? (
        <div className="grid min-h-[300px] place-items-center rounded-xl border border-dashed border-border text-center">
          <div>
            <ShieldCheck className="mx-auto h-9 w-9 text-muted" />
            <h3 className="mt-3 text-lg font-bold text-white">
              No screening decisions yet
            </h3>
            <p className="mt-1 text-sm text-muted">
              Decisions appear here after a screening-enabled search.
            </p>
          </div>
        </div>
      ) : (
        <div className="grid gap-3">
          {entries.map((entry) => {
            const busy = busyId === entry.id;
            return (
              <article
                key={entry.id}
                className="rounded-xl border border-border bg-white/[0.025] p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[10px] font-black uppercase",
                          entry.decision === "keep"
                            ? "bg-emerald-500/15 text-emerald-300"
                            : entry.decision === "reject"
                              ? "bg-red-500/15 text-red-300"
                              : "bg-amber-500/15 text-amber-200",
                        )}
                      >
                        {entry.decision}
                      </span>
                      {entry.manuallyAllowedAt ? (
                        <span className="text-[10px] font-bold text-violet-300">
                          Allowed manually
                        </span>
                      ) : null}
                    </div>
                    <h3 className="mt-2 text-sm font-bold text-white">
                      {entry.title || entry.jobId}
                    </h3>
                    <p className="mt-0.5 text-xs text-muted">
                      {entry.company || "Unknown company"}
                    </p>
                  </div>
                  <time className="text-[10px] text-muted">
                    {formatAuditTime(entry.checkedAt)}
                  </time>
                </div>
                <div className="mt-3 rounded-lg border border-white/[0.06] bg-black/10 p-3">
                  <p className="text-xs font-bold text-[#dde4ee]">
                    {entry.reasonCode}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-muted">
                    {entry.reason}
                  </p>
                  {entry.matchedRuleIds.length ? (
                    <p className="mt-2 text-[10px] text-violet-300">
                      Matched rules: {entry.matchedRuleIds.join(", ")}
                    </p>
                  ) : null}
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <p className="text-[10px] text-muted">
                    {entry.model} · config {entry.configHash.slice(0, 10)} ·{" "}
                    {entry.promptVersion}
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    {entry.sourceUrl ? (
                      <a
                        href={entry.sourceUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-[10px] font-bold text-muted hover:text-white"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        Source
                      </a>
                    ) : null}
                    {entry.canRecheck ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => onRecheck(entry)}
                      >
                        {busy ? (
                          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <RotateCcw className="h-3.5 w-3.5" />
                        )}
                        Recheck
                      </Button>
                    ) : null}
                    {entry.canAllowManually ? (
                      <Button
                        size="sm"
                        disabled={busy}
                        onClick={() => onAllow(entry)}
                      >
                        <Check className="h-3.5 w-3.5" />
                        Allow manually
                      </Button>
                    ) : null}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AutoSearchForm({
  draft,
  configs,
  saving,
  onChange,
  onCancel,
  onSave,
}: {
  draft: ScheduleDraft;
  configs: JobSearchConfig[];
  saving: boolean;
  onChange: (draft: ScheduleDraft) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  function patch(update: Partial<ScheduleDraft>) {
    onChange({ ...draft, ...update });
  }

  function toggleSeniority(
    field: "allowedSeniority" | "excludedSeniority",
    value: ScreeningSeniority,
  ) {
    const opposite =
      field === "allowedSeniority"
        ? "excludedSeniority"
        : "allowedSeniority";
    const selected = draft[field].includes(value);
    patch({
      screeningTouched: true,
      [field]: selected
        ? draft[field].filter((item) => item !== value)
        : [...draft[field], value],
      [opposite]: selected
        ? draft[opposite]
        : draft[opposite].filter((item) => item !== value),
    });
  }

  function updateHardRule(
    id: string,
    update: Partial<ScreeningHardRuleDraft>,
  ) {
    patch({
      screeningTouched: true,
      hardRules: draft.hardRules.map((rule) =>
        rule.id === id ? { ...rule, ...update } : rule,
      ),
    });
  }

  return (
    <form
      className="job-scroll min-h-0 flex-1 overflow-y-auto"
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      <div className="grid gap-5 px-4 py-5 sm:px-6 lg:grid-cols-2">
        <FormSection title="Rule">
          <Field label="Rule name">
            <input
              autoFocus
              aria-label="Rule name"
              value={draft.name}
              onChange={(event) => patch({ name: event.target.value })}
              className={inputClass}
              placeholder="LinkedIn lunchtime search"
            />
          </Field>

          <Field label="Sources">
            <div className="grid grid-cols-3 gap-2">
              {sourceOptions.map((source) => {
                const selected = draft.sources.includes(source.id);
                return (
                  <button
                    key={source.id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() =>
                      patch({
                        sources: selected
                          ? draft.sources.filter((item) => item !== source.id)
                          : [...draft.sources, source.id],
                      })
                    }
                    className={cn(
                      "h-10 rounded-lg border text-xs font-bold transition",
                      selected
                        ? "border-violet-400/70 bg-violet-500/15 text-white"
                        : "border-border bg-white/[0.025] text-muted hover:bg-white/[0.06] hover:text-white",
                    )}
                  >
                    {selected ? <Check className="mr-1 inline h-3.5 w-3.5" /> : null}
                    {source.label}
                  </button>
                );
              })}
            </div>
          </Field>

          <Field label="Enabled">
            <button
              type="button"
              role="switch"
              aria-label="Enabled"
              aria-checked={draft.enabled}
              onClick={() => patch({ enabled: !draft.enabled })}
              className="flex h-10 w-full items-center justify-between rounded-lg border border-border bg-white/[0.025] px-3 text-xs font-bold text-[#dce3ec]"
            >
              Run this rule automatically
              <Toggle enabled={draft.enabled} />
            </button>
          </Field>
        </FormSection>

        <FormSection title="Search config">
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              aria-pressed={!draft.createConfig}
              disabled={configs.length === 0}
              onClick={() => {
                const config =
                  configs.find((item) => item.id === draft.configId) ?? configs[0];
                if (!config) return;
                const next = { ...draft, createConfig: false };
                applyConfigToDraft(next, config);
                onChange(next);
              }}
              className={choiceClass(!draft.createConfig)}
            >
              Existing config
            </button>
            <button
              type="button"
              aria-pressed={draft.createConfig}
              onClick={() => patch({ createConfig: true, configId: "" })}
              className={choiceClass(draft.createConfig)}
            >
              New config
            </button>
          </div>

          {draft.createConfig ? (
            <>
              <Field label="Config name">
                <input
                  aria-label="Config name"
                  value={draft.configName}
                  onChange={(event) => patch({ configName: event.target.value })}
                  className={inputClass}
                  placeholder="Zurich engineering roles"
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Keywords">
                  <input
                    aria-label="Keywords"
                    value={draft.keywords}
                    onChange={(event) => patch({ keywords: event.target.value })}
                    className={inputClass}
                    placeholder="Software Engineer"
                  />
                </Field>
                <Field label="Location">
                  <input
                    aria-label="Location"
                    value={draft.location}
                    onChange={(event) => patch({ location: event.target.value })}
                    className={inputClass}
                    placeholder="Zurich"
                  />
                </Field>
              </div>
            </>
          ) : (
            <Field label="Config">
              <select
                aria-label="Config"
                value={draft.configId}
                onChange={(event) => {
                  const config = configs.find(
                    (item) => item.id === event.target.value,
                  );
                  if (!config) return;
                  const next = { ...draft };
                  applyConfigToDraft(next, config);
                  onChange(next);
                }}
                className={inputClass}
              >
                {configs.map((config) => (
                  <option key={config.id} value={config.id}>
                    {config.name}
                  </option>
                ))}
              </select>
            </Field>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Results limit">
              <input
                type="number"
                aria-label="Results limit"
                min={1}
                max={1000}
                value={draft.resultsLimit}
                onChange={(event) => patch({ resultsLimit: event.target.value })}
                className={inputClass}
              />
            </Field>
            <Field label="Deduplication">
              <button
                type="button"
                role="switch"
                aria-label="Deduplication"
                aria-checked={draft.deduplicate}
                onClick={() => patch({ deduplicate: !draft.deduplicate })}
                className="flex h-10 w-full items-center justify-between rounded-lg border border-border bg-white/[0.025] px-3 text-xs font-bold text-[#dce3ec]"
              >
                Remove repeats
                <Toggle enabled={draft.deduplicate} />
              </button>
            </Field>
          </div>
          {!draft.createConfig ? (
            <p className="text-[10px] leading-4 text-muted">
              Limit and deduplication belong to this config and apply to every rule
              that uses it.
            </p>
          ) : null}
        </FormSection>

        <FormSection title="Screening" className="lg:col-span-2">
          <Field label="Pre-screening">
            <button
              type="button"
              role="switch"
              aria-label="Pre-screening"
              aria-checked={draft.screeningEnabled}
              onClick={() =>
                patch({
                  screeningTouched: true,
                  screeningEnabled: !draft.screeningEnabled,
                })
              }
              className="flex min-h-12 w-full items-center justify-between rounded-lg border border-border bg-white/[0.025] px-3 text-left"
            >
              <span>
                <span className="block text-xs font-bold text-[#dce3ec]">
                  Filter vacancies before saving
                </span>
                <span className="mt-0.5 block text-[10px] text-muted">
                  Only vacancies that pass screening are shown and analyzed.
                </span>
              </span>
              <Toggle enabled={draft.screeningEnabled} />
            </button>
          </Field>

          {draft.screeningEnabled ? (
            <>
              <div className="grid gap-3 lg:grid-cols-2">
                <Field label="Target professions">
                  <textarea
                    aria-label="Target professions"
                    value={draft.targetRoles}
                    onChange={(event) =>
                      patch({
                        screeningTouched: true,
                        targetRoles: event.target.value,
                      })
                    }
                    className={textareaClass}
                    placeholder={"Software Engineer\nBackend Engineer"}
                  />
                  <span className="text-[10px] leading-4 text-muted">
                    One profession per line or separated by commas.
                  </span>
                </Field>
                <Field label="Excluded professions">
                  <textarea
                    aria-label="Excluded professions"
                    value={draft.excludedRoles}
                    onChange={(event) =>
                      patch({
                        screeningTouched: true,
                        excludedRoles: event.target.value,
                      })
                    }
                    className={textareaClass}
                    placeholder={"Sales Manager\nRecruiter"}
                  />
                  <span className="text-[10px] leading-4 text-muted">
                    Clear role conflicts are rejected before persistence.
                  </span>
                </Field>
              </div>

              <div className="grid gap-3 lg:grid-cols-2">
                <SeniorityPicker
                  label="Allowed seniority"
                  selected={draft.allowedSeniority}
                  onToggle={(value) =>
                    toggleSeniority("allowedSeniority", value)
                  }
                />
                <SeniorityPicker
                  label="Excluded seniority"
                  selected={draft.excludedSeniority}
                  onToggle={(value) =>
                    toggleSeniority("excludedSeniority", value)
                  }
                />
              </div>

              <Field label="Hard rules">
                <div className="grid gap-2">
                  {draft.hardRules.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-border bg-black/10 px-3 py-4 text-center text-[11px] text-muted">
                      No additional hard rules.
                    </div>
                  ) : (
                    draft.hardRules.map((rule, index) => (
                      <div
                        key={rule.id}
                        className="grid gap-2 rounded-lg border border-border bg-black/10 p-2.5 lg:grid-cols-[minmax(130px,.8fr)_minmax(150px,1fr)_minmax(160px,1.4fr)_auto_auto] lg:items-center"
                      >
                        <select
                          aria-label={`Hard rule ${index + 1} field`}
                          value={rule.field}
                          onChange={(event) =>
                            updateHardRule(rule.id, {
                              field: event.target.value,
                            })
                          }
                          className={inputClass}
                        >
                          {!screeningFieldOptions.some(
                            ([value]) => value === rule.field,
                          ) ? (
                            <option value={rule.field}>{rule.field}</option>
                          ) : null}
                          {screeningFieldOptions.map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                        <select
                          aria-label={`Hard rule ${index + 1} operator`}
                          value={rule.operator}
                          onChange={(event) =>
                            updateHardRule(rule.id, {
                              operator: event.target.value,
                            })
                          }
                          className={inputClass}
                        >
                          {!screeningOperatorOptions.some(
                            ([value]) => value === rule.operator,
                          ) ? (
                            <option value={rule.operator}>
                              {rule.operator}
                            </option>
                          ) : null}
                          {screeningOperatorOptions.map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                        <input
                          aria-label={`Hard rule ${index + 1} value`}
                          value={rule.value}
                          onChange={(event) =>
                            updateHardRule(rule.id, {
                              value: event.target.value,
                            })
                          }
                          className={inputClass}
                          placeholder="Rule value"
                        />
                        <button
                          type="button"
                          role="switch"
                          aria-label={`Hard rule ${index + 1} enabled`}
                          aria-checked={rule.enabled}
                          onClick={() =>
                            updateHardRule(rule.id, {
                              enabled: !rule.enabled,
                            })
                          }
                          className="flex h-10 items-center justify-center rounded-lg border border-border px-3"
                        >
                          <Toggle enabled={rule.enabled} />
                        </button>
                        <IconAction
                          label={`Remove hard rule ${index + 1}`}
                          danger
                          onClick={() =>
                            patch({
                              screeningTouched: true,
                              hardRules: draft.hardRules.filter(
                                (item) => item.id !== rule.id,
                              ),
                            })
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </IconAction>
                      </div>
                    ))
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    className="justify-self-start"
                    onClick={() =>
                      patch({
                        screeningTouched: true,
                        hardRules: [
                          ...draft.hardRules,
                          newHardRuleDraft(),
                        ],
                      })
                    }
                  >
                    <Plus className="h-4 w-4" />
                    Add hard rule
                  </Button>
                </div>
              </Field>
            </>
          ) : (
            <p className="text-[10px] leading-4 text-muted">
              Screening is off. Parser results are saved using the existing
              search behavior.
            </p>
          )}
        </FormSection>

        <FormSection title="Days and time">
          <Field label="Frequency">
            <div className="grid grid-cols-3 gap-2">
              {(
                [
                  ["daily", "Daily"],
                  ["weekdays", "Weekdays"],
                  ["selected_days", "Custom"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={draft.frequency === value}
                  onClick={() =>
                    patch({
                      frequency: value,
                      weekdays:
                        value === "weekdays"
                          ? [0, 1, 2, 3, 4]
                          : draft.weekdays,
                    })
                  }
                  className={choiceClass(draft.frequency === value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </Field>

          {draft.frequency === "selected_days" ? (
            <Field label="Run on">
              <div className="grid grid-cols-7 gap-1.5">
                {weekdayOptions.map((day) => {
                  const selected = draft.weekdays.includes(day.id);
                  return (
                    <button
                      key={day.id}
                      type="button"
                      title={day.label}
                      aria-pressed={selected}
                      onClick={() =>
                        patch({
                          weekdays: selected
                            ? draft.weekdays.filter((item) => item !== day.id)
                            : [...draft.weekdays, day.id].sort(),
                        })
                      }
                      className={cn(
                        "h-9 rounded-lg border text-[10px] font-bold transition",
                        selected
                          ? "border-violet-400/70 bg-violet-500/15 text-white"
                          : "border-border bg-white/[0.025] text-muted",
                      )}
                    >
                      {day.short}
                    </button>
                  );
                })}
              </div>
            </Field>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Local time">
              <input
                type="time"
                aria-label="Local time"
                value={draft.localTime}
                onChange={(event) => patch({ localTime: event.target.value })}
                className={inputClass}
              />
            </Field>
            <Field label="Timezone">
              <input
                list="auto-search-timezones"
                aria-label="Timezone"
                value={draft.timezone}
                onChange={(event) => patch({ timezone: event.target.value })}
                className={inputClass}
                placeholder="Europe/Zurich"
              />
              <datalist id="auto-search-timezones">
                {timezoneSuggestions.map((timezone) => (
                  <option key={timezone} value={timezone} />
                ))}
              </datalist>
            </Field>
          </div>
          <p className="text-[10px] leading-4 text-muted">
            Need another run time? Duplicate this rule and change its source or
            time.
          </p>
        </FormSection>

        <FormSection title="Analysis">
          <Field label="AI Match">
            <button
              type="button"
              role="switch"
              aria-label="AI Match"
              aria-checked={draft.aiAnalysisEnabled}
              onClick={() =>
                patch({ aiAnalysisEnabled: !draft.aiAnalysisEnabled })
              }
              className="flex min-h-12 w-full items-center justify-between rounded-lg border border-border bg-white/[0.025] px-3 text-left"
            >
              <span>
                <span className="block text-xs font-bold text-[#dce3ec]">
                  Analyze new vacancies
                </span>
                <span className="mt-0.5 block text-[10px] text-muted">
                  Requires current AI data-processing consent.
                </span>
              </span>
              <Toggle enabled={draft.aiAnalysisEnabled} />
            </button>
          </Field>

          <div className="rounded-lg border border-violet-400/15 bg-violet-500/[0.055] p-3 text-[11px] leading-5 text-[#c9c3db]">
            Example: duplicate “LinkedIn · 13:00”, select Indeed, set 15:00, and
            save. Each time remains an independent rule.
          </div>
        </FormSection>
      </div>

      <footer className="sticky bottom-0 flex justify-end gap-2 border-t border-border bg-[#101720]/95 px-4 py-3 backdrop-blur sm:px-6">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
          {draft.mode === "edit"
            ? "Save changes"
            : draft.mode === "duplicate"
              ? "Create duplicate"
              : "Create auto-search"}
        </Button>
      </footer>
    </form>
  );
}

function FormSection({
  title,
  children,
  className,
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "grid content-start gap-3 rounded-xl border border-border bg-white/[0.018] p-4",
        className,
      )}
    >
      <h3 className="text-sm font-bold text-white">{title}</h3>
      {children}
    </section>
  );
}

function SeniorityPicker({
  label,
  selected,
  onToggle,
}: {
  label: string;
  selected: ScreeningSeniority[];
  onToggle: (value: ScreeningSeniority) => void;
}) {
  return (
    <Field label={label}>
      <div
        role="group"
        aria-label={label}
        className="flex flex-wrap gap-1.5 rounded-lg border border-border bg-black/10 p-2"
      >
        {seniorityOptions.map((option) => {
          const active = selected.includes(option.id);
          return (
            <button
              key={option.id}
              type="button"
              aria-pressed={active}
              onClick={() => onToggle(option.id)}
              className={cn(
                "rounded-md border px-2 py-1.5 text-[10px] font-bold transition",
                active
                  ? "border-violet-400/70 bg-violet-500/15 text-white"
                  : "border-border bg-white/[0.025] text-muted hover:text-white",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </Field>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <span className="text-[11px] font-bold text-[#cbd3df]">{label}</span>
      {children}
    </div>
  );
}

function ListField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <span className="mb-1 block text-[9px] font-bold uppercase tracking-[0.08em] text-muted">
        {label}
      </span>
      {children}
    </div>
  );
}

function IconAction({
  label,
  danger = false,
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid h-8 w-8 place-items-center rounded-lg border border-border text-muted transition hover:bg-white/[0.07] hover:text-white disabled:cursor-not-allowed disabled:opacity-45",
        danger && "hover:border-red-400/30 hover:bg-red-500/10 hover:text-red-200",
      )}
    >
      {children}
    </button>
  );
}

function Toggle({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={cn(
        "flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition",
        enabled ? "justify-end bg-violet-500" : "justify-start bg-slate-700",
      )}
    >
      <span className="h-4 w-4 rounded-full bg-white shadow" />
    </span>
  );
}

function draftFromSchedule(
  schedule: JobSearchSchedule,
  config: JobSearchConfig | undefined,
  mode: EditorMode,
): ScheduleDraft {
  const draft = defaultDraft();
  draft.id = schedule.id;
  draft.mode = mode;
  draft.name = schedule.name;
  draft.sources = [...schedule.sources];
  draft.frequency = schedule.frequency;
  draft.weekdays = [...schedule.weekdays];
  draft.localTime = schedule.localTime.slice(0, 5);
  draft.timezone = schedule.timezone;
  draft.aiAnalysisEnabled = schedule.aiAnalysisEnabled;
  draft.enabled = schedule.enabled;
  if (config) {
    applyConfigToDraft(draft, config);
    draft.createConfig = false;
  }
  return draft;
}

function applyConfigToDraft(
  draft: ScheduleDraft,
  config: JobSearchConfig,
) {
  const { search, screening } = configSections(config.filters);
  draft.configId = config.id;
  draft.configName = config.name;
  draft.keywords = stringFilter(search, "keywords", "query");
  draft.location = stringFilter(search, "location");
  draft.resultsLimit = String(
    numberFilter(search, "resultsLimit", "results_limit") ?? 50,
  );
  draft.deduplicate =
    booleanFilter(search, "deduplicate") ?? true;
  draft.screeningTouched = false;
  draft.screeningEnabled =
    booleanFilter(screening, "enabled") ?? false;
  draft.targetRoles = stringListFilter(
    screening,
    "targetRoles",
    "target_roles",
  ).join("\n");
  draft.excludedRoles = stringListFilter(
    screening,
    "excludedRoles",
    "excluded_roles",
  ).join("\n");
  draft.allowedSeniority = seniorityListFilter(
    screening,
    "allowedSeniority",
    "allowed_seniority",
  );
  draft.excludedSeniority = seniorityListFilter(
    screening,
    "excludedSeniority",
    "excluded_seniority",
  );
  draft.hardRules = hardRulesFromConfig(screening);
}

async function saveConfigForDraft(
  draft: ScheduleDraft,
  configs: Map<string, JobSearchConfig>,
): Promise<string> {
  const limit = Number.parseInt(draft.resultsLimit, 10);
  if (draft.createConfig) {
    const config = await requestJson<JobSearchConfig>("/job-search/configs", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        name: draft.configName.trim(),
        filters: createVersionedFilters(draft, limit),
      }),
    });
    return config.id;
  }

  const config = configs.get(draft.configId);
  if (!config) throw new Error("Select an available search config");
  if (!configHasEditableChanges(config.filters, draft, limit)) {
    return config.id;
  }
  const currentConfig = await requestJson<JobSearchConfig>(
    `/job-search/configs/${encodeURIComponent(config.id)}`,
  );
  const nextFilters = updateVersionedFilters(
    currentConfig.filters,
    draft,
    limit,
  );
  if (JSON.stringify(nextFilters) !== JSON.stringify(currentConfig.filters)) {
    await requestJson<JobSearchConfig>(
      `/job-search/configs/${encodeURIComponent(config.id)}`,
      {
        method: "PATCH",
        headers: jsonHeaders,
        body: JSON.stringify({ filters: nextFilters }),
      },
    );
  }
  return config.id;
}

function configHasEditableChanges(
  filters: Record<string, unknown>,
  draft: ScheduleDraft,
  limit: number,
): boolean {
  const { search, screening } = configSections(filters);
  const searchChanged =
    (numberFilter(search, "resultsLimit", "results_limit") ?? 50) !== limit ||
    (booleanFilter(search, "deduplicate") ?? true) !== draft.deduplicate;
  if (searchChanged) return true;
  if (!draft.screeningTouched) return false;
  return JSON.stringify(editableScreeningState(screening)) !== JSON.stringify({
    enabled: draft.screeningEnabled,
    targetRoles: splitList(draft.targetRoles),
    excludedRoles: splitList(draft.excludedRoles),
    allowedSeniority: draft.allowedSeniority,
    excludedSeniority: draft.excludedSeniority,
    hardRules: draft.hardRules.map((rule) => ({
      field: rule.field,
      operator: rule.operator,
      value: serializeHardRule(rule).value,
      enabled: rule.enabled,
    })),
  });
}

function editableScreeningState(
  screening: Record<string, unknown>,
): Record<string, unknown> {
  return {
    enabled: booleanFilter(screening, "enabled") ?? false,
    targetRoles: stringListFilter(
      screening,
      "targetRoles",
      "target_roles",
    ),
    excludedRoles: stringListFilter(
      screening,
      "excludedRoles",
      "excluded_roles",
    ),
    allowedSeniority: seniorityListFilter(
      screening,
      "allowedSeniority",
      "allowed_seniority",
    ),
    excludedSeniority: seniorityListFilter(
      screening,
      "excludedSeniority",
      "excluded_seniority",
    ),
    hardRules: hardRulesFromConfig(screening).map((rule) => ({
      field: rule.field,
      operator: rule.operator,
      value: serializeHardRule(rule).value,
      enabled: rule.enabled,
    })),
  };
}

function createVersionedFilters(
  draft: ScheduleDraft,
  limit: number,
): Record<string, unknown> {
  return {
    schemaVersion: 2,
    search: {
      keywords: draft.keywords.trim(),
      location: draft.location.trim(),
      resultsLimit: limit,
      deduplicate: draft.deduplicate,
    },
    screening: screeningPayload(draft, {}),
  };
}

function updateVersionedFilters(
  filters: Record<string, unknown>,
  draft: ScheduleDraft,
  limit: number,
): Record<string, unknown> {
  const versioned = isRecord(filters.search) || isRecord(filters.screening);
  const { search, screening } = configSections(filters);
  const root = versioned ? { ...filters } : {};
  return {
    ...root,
    schemaVersion: 2,
    search: {
      ...search,
      resultsLimit: limit,
      deduplicate: draft.deduplicate,
    },
    screening: draft.screeningTouched
      ? screeningPayload(draft, screening)
      : screening,
  };
}

function screeningPayload(
  draft: ScheduleDraft,
  original: Record<string, unknown>,
): Record<string, unknown> {
  return {
    ...original,
    enabled: draft.screeningEnabled,
    targetRoles: splitList(draft.targetRoles),
    excludedRoles: splitList(draft.excludedRoles),
    allowedSeniority: draft.allowedSeniority,
    excludedSeniority: draft.excludedSeniority,
    hardRules: draft.hardRules.map(serializeHardRule),
  };
}

function serializeHardRule(
  rule: ScreeningHardRuleDraft,
): Record<string, unknown> {
  const originalValue = rule.original.value;
  let value: unknown = rule.value.trim();
  if (displayRuleValue(originalValue) === rule.value) {
    value = originalValue;
  } else if (rule.operator === "in" || rule.operator === "notIn") {
    value = splitList(rule.value);
  } else if (
    screeningFieldOptions
      .map(([field]) => field)
      .includes(rule.field as (typeof screeningFieldOptions)[number][0]) &&
    (rule.field === "salaryMin" || rule.field === "salaryMax") &&
    rule.value.trim() !== "" &&
    Number.isFinite(Number(rule.value))
  ) {
    value = Number(rule.value);
  }
  return {
    ...rule.original,
    field: rule.field,
    operator: rule.operator,
    value,
    enabled: rule.enabled,
  };
}

function configSections(filters: Record<string, unknown>): {
  search: Record<string, unknown>;
  screening: Record<string, unknown>;
} {
  return {
    search: isRecord(filters.search) ? filters.search : filters,
    screening: isRecord(filters.screening) ? filters.screening : {},
  };
}

function hardRulesFromConfig(
  screening: Record<string, unknown>,
): ScreeningHardRuleDraft[] {
  const value = screening.hardRules ?? screening.hard_rules;
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((rule) => newHardRuleDraft(rule));
}

let hardRuleDraftSequence = 0;

function newHardRuleDraft(
  original: Record<string, unknown> = {},
): ScreeningHardRuleDraft {
  hardRuleDraftSequence += 1;
  return {
    id: `screening-rule-${hardRuleDraftSequence}`,
    field:
      typeof original.field === "string" ? original.field : "title",
    operator:
      typeof original.operator === "string"
        ? original.operator
        : "contains",
    value: displayRuleValue(original.value),
    enabled:
      typeof original.enabled === "boolean" ? original.enabled : true,
    original: { ...original },
  };
}

function displayRuleValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value
      .filter((item): item is string => typeof item === "string")
      .join(", ");
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  return "";
}

function screeningSummary(filters: Record<string, unknown>): string {
  const { screening } = configSections(filters);
  if (!(booleanFilter(screening, "enabled") ?? false)) {
    return "Screening off";
  }
  const targetCount = stringListFilter(
    screening,
    "targetRoles",
    "target_roles",
  ).length;
  const excludedCount = stringListFilter(
    screening,
    "excludedRoles",
    "excluded_roles",
  ).length;
  const seniorityCount =
    seniorityListFilter(
      screening,
      "allowedSeniority",
      "allowed_seniority",
    ).length +
    seniorityListFilter(
      screening,
      "excludedSeniority",
      "excluded_seniority",
    ).length;
  const rawHardRules = screening.hardRules ?? screening.hard_rules;
  const hardRuleCount = Array.isArray(rawHardRules)
    ? rawHardRules.filter(
        (rule) =>
          isRecord(rule) &&
          (typeof rule.enabled !== "boolean" || rule.enabled),
      ).length
    : 0;
  const parts = [
    targetCount ? `${targetCount} target role${targetCount === 1 ? "" : "s"}` : "",
    excludedCount
      ? `${excludedCount} excluded role${excludedCount === 1 ? "" : "s"}`
      : "",
    seniorityCount ? `${seniorityCount} seniority filter${seniorityCount === 1 ? "" : "s"}` : "",
    hardRuleCount ? `${hardRuleCount} hard rule${hardRuleCount === 1 ? "" : "s"}` : "",
  ].filter(Boolean);
  return `Screening on${parts.length ? ` · ${parts.join(" · ")}` : ""}`;
}

function validateDraft(draft: ScheduleDraft): string {
  if (!draft.name.trim()) return "Rule name is required";
  if (draft.sources.length === 0) return "Select at least one source";
  if (draft.createConfig && !draft.configName.trim()) {
    return "Config name is required";
  }
  if (!draft.createConfig && !draft.configId) return "Select a search config";
  if (
    draft.frequency === "selected_days" &&
    draft.weekdays.length === 0
  ) {
    return "Select at least one day";
  }
  if (!draft.localTime) return "Local time is required";
  if (!draft.timezone.trim()) return "Timezone is required";
  const limit = Number.parseInt(draft.resultsLimit, 10);
  if (!Number.isFinite(limit) || limit < 1 || limit > 1000) {
    return "Results limit must be between 1 and 1000";
  }
  if (splitList(draft.targetRoles).length > 50) {
    return "Target professions must contain at most 50 entries";
  }
  if (splitList(draft.excludedRoles).length > 50) {
    return "Excluded professions must contain at most 50 entries";
  }
  if (
    draft.screeningEnabled &&
    draft.hardRules.some(
      (rule) =>
        !rule.field.trim() ||
        !rule.operator.trim() ||
        !rule.value.trim(),
    )
  ) {
    return "Every hard rule needs a field, operator, and value";
  }
  return "";
}

function scheduleLabel(schedule: JobSearchSchedule): string {
  const time = schedule.localTime.slice(0, 5);
  if (schedule.frequency === "daily") return `Daily · ${time}`;
  if (schedule.frequency === "weekdays") return `Weekdays · ${time}`;
  const days = schedule.weekdays
    .map((weekday) => weekdayOptions.find((item) => item.id === weekday)?.short)
    .filter(Boolean)
    .join(", ");
  return `${days || "Custom"} · ${time}`;
}

function formatNextRun(schedule: JobSearchSchedule): string {
  if (!schedule.enabled) return "Paused";
  if (!schedule.nextRunAt) return "Not scheduled";
  const value = new Date(schedule.nextRunAt);
  if (Number.isNaN(value.getTime())) return "Not scheduled";
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: schedule.timezone,
      timeZoneName: "short",
    }).format(value);
  } catch {
    return value.toLocaleString("en-US", { hour12: false });
  }
}

function sourceLabel(source: JobSearchSource): string {
  return sourceOptions.find((item) => item.id === source)?.label ?? source;
}

function localTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Zurich";
}

function withSeconds(value: string): string {
  return value.length === 5 ? `${value}:00` : value;
}

function stringFilter(
  filters: Record<string, unknown>,
  ...keys: string[]
): string {
  for (const key of keys) {
    if (typeof filters[key] === "string") return filters[key] as string;
  }
  return "";
}

function numberFilter(
  filters: Record<string, unknown>,
  ...keys: string[]
): number | null {
  for (const key of keys) {
    const value = filters[key];
    if (typeof value === "number") return value;
    if (typeof value === "string" && Number.isFinite(Number(value))) {
      return Number(value);
    }
  }
  return null;
}

function booleanFilter(
  filters: Record<string, unknown>,
  key: string,
): boolean | null {
  return typeof filters[key] === "boolean" ? filters[key] : null;
}

function stringListFilter(
  filters: Record<string, unknown>,
  ...keys: string[]
): string[] {
  for (const key of keys) {
    const value = filters[key];
    if (Array.isArray(value)) {
      return value.filter(
        (item): item is string => typeof item === "string",
      );
    }
  }
  return [];
}

function seniorityListFilter(
  filters: Record<string, unknown>,
  ...keys: string[]
): ScreeningSeniority[] {
  const allowed = new Set<ScreeningSeniority>(
    seniorityOptions.map((option) => option.id),
  );
  return stringListFilter(filters, ...keys).filter(
    (value): value is ScreeningSeniority =>
      allowed.has(value as ScreeningSeniority),
  );
}

function splitList(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function formatAuditTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("en-US", {
        dateStyle: "medium",
        timeStyle: "short",
        hour12: false,
      }).format(date);
}

const jsonHeaders = { "Content-Type": "application/json" };
const inputClass =
  "h-10 w-full rounded-lg border border-border bg-[#0b1118] px-3 text-xs font-semibold text-white outline-none placeholder:text-muted/60 focus:border-violet-400/70";
const textareaClass =
  "min-h-20 w-full resize-y rounded-lg border border-border bg-[#0b1118] px-3 py-2 text-xs font-semibold text-white outline-none placeholder:text-muted/60 focus:border-violet-400/70";

function choiceClass(selected: boolean): string {
  return cn(
    "h-9 rounded-lg border text-xs font-bold transition disabled:cursor-not-allowed disabled:opacity-40",
    selected
      ? "border-violet-400/70 bg-violet-500/15 text-white"
      : "border-border bg-white/[0.025] text-muted hover:bg-white/[0.06] hover:text-white",
  );
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    cache: "no-store",
    ...init,
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as {
        detail?: string | { message?: string };
      };
      detail =
        typeof payload.detail === "string"
          ? payload.detail
          : payload.detail?.message ?? detail;
    } catch {
      // Keep the HTTP fallback when the response is not JSON.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Automatic search request failed";
}
