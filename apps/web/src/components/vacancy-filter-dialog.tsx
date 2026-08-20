"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

type VacancySeniority = (typeof seniorityOptions)[number]["id"];

export type VacancyFilterSettings = {
  schemaVersion: number;
  enabled: boolean;
  allowedSeniority: VacancySeniority[];
  excludedSeniority: VacancySeniority[];
  targetTechnologies: string[];
  excludedTechnologies: string[];
  updatedAt?: string | null;
};

type VacancyFilterDraft = Omit<
  VacancyFilterSettings,
  "targetTechnologies" | "excludedTechnologies" | "updatedAt"
> & {
  targetTechnologies: string;
  excludedTechnologies: string;
  updatedAt: string;
};

type DialogStatus =
  | "idle"
  | "loading"
  | "saving"
  | "load-error"
  | "save-error";

type VacancyFilterDialogProps = {
  open: boolean;
  onClose: () => void;
};

const defaultSettings: VacancyFilterSettings = {
  schemaVersion: 1,
  enabled: false,
  allowedSeniority: [],
  excludedSeniority: [],
  targetTechnologies: [],
  excludedTechnologies: [],
  updatedAt: "",
};

export function VacancyFilterDialog({
  open,
  onClose,
}: VacancyFilterDialogProps) {
  const [draft, setDraft] = useState<VacancyFilterDraft>(() =>
    settingsToDraft(defaultSettings),
  );
  const [status, setStatus] = useState<DialogStatus>("idle");
  const [message, setMessage] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    const returnFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    closeButtonRef.current?.focus();

    return () => returnFocus?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const abortController = new AbortController();
    setStatus("loading");
    setMessage("");

    void requestJson<unknown>("/job-search/filter-settings", {
      signal: abortController.signal,
    })
      .then((payload) => {
        setDraft(settingsToDraft(normalizeSettings(payload)));
        setStatus("idle");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setStatus("load-error");
        setMessage(errorMessage(error));
      });

    return () => abortController.abort();
  }, [loadAttempt, open]);

  useEffect(() => {
    if (!open) return;

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && status !== "saving") onClose();
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open, status]);

  const targetTechnologies = useMemo(
    () => splitEntries(draft.targetTechnologies),
    [draft.targetTechnologies],
  );
  const excludedTechnologies = useMemo(
    () => splitEntries(draft.excludedTechnologies),
    [draft.excludedTechnologies],
  );
  const summary = filterSummary(
    draft,
    targetTechnologies,
    excludedTechnologies,
  );

  if (!open) return null;

  function toggleSeniority(
    field: "allowedSeniority" | "excludedSeniority",
    value: VacancySeniority,
  ) {
    const opposite =
      field === "allowedSeniority"
        ? "excludedSeniority"
        : "allowedSeniority";
    const selected = draft[field].includes(value);

    setDraft((current) => ({
      ...current,
      [field]: selected
        ? current[field].filter((item) => item !== value)
        : orderSeniority([...current[field], value]),
      [opposite]: selected
        ? current[opposite]
        : current[opposite].filter((item) => item !== value),
    }));
    setStatus("idle");
    setMessage("");
  }

  async function saveSettings() {
    const validationMessage = validateTechnologies(
      targetTechnologies,
      excludedTechnologies,
    );
    if (validationMessage) {
      setStatus("save-error");
      setMessage(validationMessage);
      return;
    }

    setStatus("saving");
    setMessage("");
    try {
      const saved = await requestJson<unknown>("/job-search/filter-settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          schemaVersion: draft.schemaVersion,
          enabled: draft.enabled,
          allowedSeniority: draft.allowedSeniority,
          excludedSeniority: draft.excludedSeniority,
          targetTechnologies,
          excludedTechnologies,
        }),
      });
      setDraft(settingsToDraft(normalizeSettings(saved)));
      setStatus("idle");
      onClose();
    } catch (error) {
      setStatus("save-error");
      setMessage(errorMessage(error));
    }
  }

  const isSaving = status === "saving";

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-3 backdrop-blur-sm sm:p-5"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isSaving) onClose();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="vacancy-filter-dialog-title"
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          trapFocus(event, dialogRef.current);
        }}
        className="panel flex max-h-[calc(100vh-24px)] w-full max-w-[880px] flex-col overflow-hidden border-white/[0.11] bg-[#101720]/98 shadow-[0_28px_90px_rgba(0,0,0,0.62)] sm:max-h-[calc(100vh-40px)]"
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-4 py-4 sm:px-6">
          <div className="flex min-w-0 items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-violet-500/15 text-violet-300">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2
                id="vacancy-filter-dialog-title"
                className="text-xl font-bold text-white sm:text-2xl"
              >
                Vacancy Filter
              </h2>
              <p className="mt-1 text-xs font-medium leading-5 text-muted sm:text-sm">
                Applied to every vacancy after search and before saving or AI
                analysis.
              </p>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="Close vacancy filter"
            disabled={isSaving}
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-muted transition hover:bg-white/[0.08] hover:text-white disabled:cursor-not-allowed disabled:opacity-45"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        {status === "loading" ? (
          <div className="grid min-h-[420px] flex-1 place-items-center text-muted">
            <div className="text-center">
              <LoaderCircle className="mx-auto h-6 w-6 animate-spin" />
              <p className="mt-3 text-xs font-semibold">
                Loading filter settings...
              </p>
            </div>
          </div>
        ) : status === "load-error" ? (
          <div className="grid min-h-[420px] flex-1 place-items-center p-6 text-center">
            <div className="max-w-md">
              <AlertTriangle className="mx-auto h-8 w-8 text-red-300" />
              <h3 className="mt-3 text-base font-bold text-white">
                Filter settings could not be loaded
              </h3>
              <p role="alert" className="mt-2 text-sm leading-6 text-red-200">
                {message}
              </p>
              <Button
                type="button"
                variant="ghost"
                className="mt-5 border border-border"
                onClick={() => setLoadAttempt((attempt) => attempt + 1)}
              >
                <RotateCcw className="h-4 w-4" />
                Retry
              </Button>
            </div>
          </div>
        ) : (
          <form
            className="job-scroll min-h-0 flex-1 overflow-y-auto"
            onSubmit={(event) => {
              event.preventDefault();
              void saveSettings();
            }}
          >
            <div className="grid gap-4 px-4 py-5 sm:px-6">
              <section className="rounded-xl border border-border bg-white/[0.018] p-4">
                <button
                  type="button"
                  role="switch"
                  aria-label="Filter incoming vacancies"
                  aria-checked={draft.enabled}
                  onClick={() => {
                    setDraft((current) => ({
                      ...current,
                      enabled: !current.enabled,
                    }));
                    setStatus("idle");
                    setMessage("");
                  }}
                  className="flex min-h-14 w-full items-center justify-between gap-4 text-left"
                >
                  <span>
                    <span className="block text-sm font-bold text-white">
                      Filter incoming vacancies
                    </span>
                    <span className="mt-1 block text-[11px] leading-5 text-muted">
                      Turning this off keeps the criteria below, but does not apply
                      them to new search results.
                    </span>
                  </span>
                  <Toggle enabled={draft.enabled} />
                </button>
              </section>

              <section className="grid gap-4 rounded-xl border border-border bg-white/[0.018] p-4">
                <div>
                  <h3 className="text-sm font-bold text-white">Seniority</h3>
                  <p className="mt-1 text-[11px] leading-5 text-muted">
                    Empty groups add no global seniority restriction. A level
                    cannot be both allowed and excluded.
                  </p>
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
              </section>

              <section className="grid gap-4 rounded-xl border border-border bg-white/[0.018] p-4">
                <div>
                  <h3 className="text-sm font-bold text-white">Technology stack</h3>
                  <p className="mt-1 text-[11px] leading-5 text-muted">
                    Enter one technology per line or separate values with commas.
                    Matching is case-insensitive.
                  </p>
                </div>
                <div className="grid gap-3 lg:grid-cols-2">
                  <label className="grid gap-1.5">
                    <span className="text-[11px] font-bold text-[#cbd3df]">
                      Target technologies
                    </span>
                    <textarea
                      aria-label="Target technologies"
                      value={draft.targetTechnologies}
                      onChange={(event) => {
                        setDraft((current) => ({
                          ...current,
                          targetTechnologies: event.target.value,
                        }));
                        setStatus("idle");
                        setMessage("");
                      }}
                      className={textareaClass}
                      placeholder={"Python\nDjango\nFastAPI"}
                    />
                    <span className="text-[10px] leading-4 text-muted">
                      Keep vacancies that match at least one target technology.
                    </span>
                  </label>
                  <label className="grid gap-1.5">
                    <span className="text-[11px] font-bold text-[#cbd3df]">
                      Excluded technologies
                    </span>
                    <textarea
                      aria-label="Excluded technologies"
                      value={draft.excludedTechnologies}
                      onChange={(event) => {
                        setDraft((current) => ({
                          ...current,
                          excludedTechnologies: event.target.value,
                        }));
                        setStatus("idle");
                        setMessage("");
                      }}
                      className={textareaClass}
                      placeholder={"C#\n.NET"}
                    />
                    <span className="text-[10px] leading-4 text-muted">
                      Reject vacancies whose required stack clearly conflicts.
                    </span>
                  </label>
                </div>
              </section>

              <section
                aria-live="polite"
                className={cn(
                  "rounded-xl border p-4",
                  draft.enabled
                    ? "border-violet-400/20 bg-violet-500/[0.055]"
                    : "border-amber-400/20 bg-amber-500/[0.045]",
                )}
              >
                <p className="text-[10px] font-black uppercase tracking-[0.08em] text-muted">
                  Current behavior
                </p>
                <p className="mt-2 text-xs font-semibold leading-5 text-[#dce3ec]">
                  {summary}
                </p>
                {draft.updatedAt ? (
                  <p className="mt-2 text-[10px] text-muted">
                    Last saved {formatUpdatedAt(draft.updatedAt)}
                  </p>
                ) : null}
              </section>
            </div>

            <footer className="sticky bottom-0 border-t border-border bg-[#101720]/95 px-4 py-3 backdrop-blur sm:px-6">
              {status === "save-error" && message ? (
                <p role="alert" className="mb-3 text-xs font-semibold text-red-200">
                  {message}
                </p>
              ) : null}
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  disabled={isSaving}
                  onClick={onClose}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={isSaving}>
                  {isSaving ? (
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                  ) : null}
                  {isSaving ? "Saving..." : "Save filter"}
                </Button>
              </div>
            </footer>
          </form>
        )}
      </section>
    </div>
  );
}

function SeniorityPicker({
  label,
  selected,
  onToggle,
}: {
  label: string;
  selected: VacancySeniority[];
  onToggle: (value: VacancySeniority) => void;
}) {
  return (
    <div className="grid gap-1.5">
      <span className="text-[11px] font-bold text-[#cbd3df]">{label}</span>
      <div
        role="group"
        aria-label={label}
        className="flex min-h-[88px] flex-wrap content-start gap-1.5 rounded-lg border border-border bg-black/10 p-2"
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
                "inline-flex h-8 items-center gap-1 rounded-md border px-2.5 text-[10px] font-bold transition",
                active
                  ? "border-violet-400/70 bg-violet-500/15 text-white"
                  : "border-border bg-white/[0.025] text-muted hover:text-white",
              )}
            >
              {active ? <Check className="h-3 w-3" /> : null}
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
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

function settingsToDraft(settings: VacancyFilterSettings): VacancyFilterDraft {
  return {
    ...settings,
    allowedSeniority: [...settings.allowedSeniority],
    excludedSeniority: [...settings.excludedSeniority],
    targetTechnologies: settings.targetTechnologies.join("\n"),
    excludedTechnologies: settings.excludedTechnologies.join("\n"),
    updatedAt: settings.updatedAt ?? "",
  };
}

function normalizeSettings(value: unknown): VacancyFilterSettings {
  const payload = isRecord(value) ? value : {};
  return {
    schemaVersion:
      typeof payload.schemaVersion === "number" ? payload.schemaVersion : 1,
    enabled: typeof payload.enabled === "boolean" ? payload.enabled : false,
    allowedSeniority: normalizeSeniority(payload.allowedSeniority),
    excludedSeniority: normalizeSeniority(payload.excludedSeniority),
    targetTechnologies: normalizeEntries(payload.targetTechnologies),
    excludedTechnologies: normalizeEntries(payload.excludedTechnologies),
    updatedAt: typeof payload.updatedAt === "string" ? payload.updatedAt : "",
  };
}

function normalizeSeniority(value: unknown): VacancySeniority[] {
  if (!Array.isArray(value)) return [];
  const allowed = new Set<VacancySeniority>(
    seniorityOptions.map((option) => option.id),
  );
  return orderSeniority(
    Array.from(
      new Set(
        value.filter(
          (item): item is VacancySeniority =>
            typeof item === "string" &&
            allowed.has(item as VacancySeniority),
        ),
      ),
    ),
  );
}

function orderSeniority(values: VacancySeniority[]): VacancySeniority[] {
  const selected = new Set(values);
  return seniorityOptions
    .map((option) => option.id)
    .filter((value) => selected.has(value));
}

function normalizeEntries(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return uniqueEntries(
    value.filter((item): item is string => typeof item === "string"),
  );
}

function splitEntries(value: string): string[] {
  return uniqueEntries(value.split(/[\n,]/));
}

function uniqueEntries(values: string[]): string[] {
  const seen = new Set<string>();
  const entries: string[] = [];
  for (const value of values) {
    const entry = value.trim().replace(/\s+/g, " ");
    const key = entry.toLocaleLowerCase();
    if (!entry || seen.has(key)) continue;
    seen.add(key);
    entries.push(entry);
  }
  return entries;
}

function validateTechnologies(target: string[], excluded: string[]): string {
  if (target.length > 50 || excluded.length > 50) {
    return "Each technology list can contain at most 50 entries";
  }
  if ([...target, ...excluded].some((technology) => technology.length > 80)) {
    return "Technology names must be at most 80 characters";
  }
  const excludedKeys = new Set(
    excluded.map((technology) => technology.toLocaleLowerCase()),
  );
  const overlap = target.find((technology) =>
    excludedKeys.has(technology.toLocaleLowerCase()),
  );
  return overlap
    ? `“${overlap}” cannot be both a target and an excluded technology`
    : "";
}

function filterSummary(
  draft: VacancyFilterDraft,
  targetTechnologies: string[],
  excludedTechnologies: string[],
): string {
  if (!draft.enabled) {
    return "The global vacancy filter is off, so these criteria are not applied. Search-specific screening still applies, and the criteria remain saved for later.";
  }

  if (
    draft.allowedSeniority.length === 0 &&
    draft.excludedSeniority.length === 0 &&
    targetTechnologies.length === 0 &&
    excludedTechnologies.length === 0
  ) {
    return "The global filter is enabled but has no criteria, so it has no effect. Search-specific screening still applies.";
  }

  const parts: string[] = [];
  if (draft.allowedSeniority.length > 0) {
    parts.push(
      `keep ${seniorityLabels(draft.allowedSeniority)} seniority vacancies`,
    );
  }
  if (targetTechnologies.length > 0) {
    parts.push(`target ${targetTechnologies.join(", ")}`);
  }
  if (draft.excludedSeniority.length > 0) {
    parts.push(`exclude ${seniorityLabels(draft.excludedSeniority)} seniority`);
  }
  if (excludedTechnologies.length > 0) {
    parts.push(`exclude ${excludedTechnologies.join(", ")}`);
  }
  return `${capitalize(parts.join("; "))}. Search-specific screening is combined with these rules.`;
}

function seniorityLabels(values: VacancySeniority[]): string {
  return values
    .map(
      (value) =>
        seniorityOptions.find((option) => option.id === value)?.label ?? value,
    )
    .join(", ");
}

function capitalize(value: string): string {
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : value;
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("en-US", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
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
      const payload = (await response.json()) as { detail?: unknown };
      detail = apiErrorDetail(payload.detail) ?? detail;
    } catch {
      // Keep the HTTP fallback when the response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function apiErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (isRecord(detail) && typeof detail.message === "string") {
    return detail.message;
  }
  if (!Array.isArray(detail)) return null;

  const messages = detail.flatMap((item) =>
    isRecord(item) && typeof item.msg === "string" ? [item.msg] : [],
  );
  return messages.length > 0 ? messages.join("; ") : null;
}

function trapFocus(
  event: React.KeyboardEvent<HTMLElement>,
  dialog: HTMLElement | null,
) {
  if (!dialog) return;
  const focusable = Array.from(
    dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    ),
  );
  if (focusable.length === 0) return;

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Vacancy filter request failed";
}

const textareaClass =
  "min-h-28 w-full resize-y rounded-lg border border-border bg-[#0b1118] px-3 py-2 text-xs font-semibold leading-5 text-white outline-none placeholder:text-muted/60 focus:border-violet-400/70";
