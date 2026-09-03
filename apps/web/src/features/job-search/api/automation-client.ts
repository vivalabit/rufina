import { apiClient } from "@/shared/api/client";

export type JobSearchSource = string;
export type JobSearchFrequency = "daily" | "weekdays" | "selected_days";

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
  presetId?: string | null;
  sources: JobSearchSource[];
  sourceConfigIds?: Record<string, string>;
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

export type JobSourceConfig = {
  id: string;
  name: string;
  configId: string;
  source: JobSearchSource;
  filters: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type JobSearchPreset = {
  id: string;
  name: string;
  configId: string;
  sources: JobSearchSource[];
  sourceConfigIds: Record<string, string>;
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

export type JobSearchScheduleRun = {
  status: string;
  jobsFound: number;
  jobsAdded: number;
  warning?: string | null;
};

function arrayOf<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

export async function fetchAutomationSearchData(signal?: AbortSignal) {
  const [configs, sourceConfigs, presets, schedules] = await Promise.all([
    apiClient.json<JobSearchConfig[]>({
      path: "/job-search/configs",
      cache: "no-store",
      signal,
    }, arrayOf<JobSearchConfig>),
    apiClient.json<JobSourceConfig[]>({
      path: "/job-search/source-configs",
      cache: "no-store",
      signal,
    }, arrayOf<JobSourceConfig>).catch(() => ({ data: [], meta: null })),
    apiClient.json<JobSearchPreset[]>({
      path: "/job-search/presets",
      cache: "no-store",
      signal,
    }, arrayOf<JobSearchPreset>).catch(() => ({ data: [], meta: null })),
    apiClient.json<JobSearchSchedule[]>({
      path: "/job-search/schedules",
      cache: "no-store",
      signal,
    }, arrayOf<JobSearchSchedule>),
  ]);
  return {
    configs: configs.data,
    sourceConfigs: sourceConfigs.data,
    presets: presets.data,
    schedules: schedules.data,
  };
}

export async function fetchScreeningAudit(limit = 200, signal?: AbortSignal) {
  return (await apiClient.json<JobScreeningAuditEntry[]>({
    path: "/job-search/screening-audit",
    query: { limit },
    cache: "no-store",
    signal,
  }, arrayOf<JobScreeningAuditEntry>)).data;
}

export async function runScreeningAuditAction(
  id: string,
  action: "recheck" | "allow",
  signal?: AbortSignal,
) {
  return (await apiClient.json<JobScreeningAuditEntry>({
    path: `/job-search/screening-audit/${encodeURIComponent(id)}/${action}`,
    method: "POST",
    signal,
  })).data;
}

export async function saveJobSearchSchedule(
  id: string | null,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return (await apiClient.json<JobSearchSchedule>({
    path: id
      ? `/job-search/schedules/${encodeURIComponent(id)}`
      : "/job-search/schedules",
    method: id ? "PATCH" : "POST",
    json: payload,
    signal,
  })).data;
}

export async function patchJobSearchSchedule(
  id: string,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
) {
  return saveJobSearchSchedule(id, payload, signal);
}

export async function runJobSearchSchedule(id: string, signal?: AbortSignal) {
  return (await apiClient.json<JobSearchScheduleRun>({
    path: `/job-search/schedules/${encodeURIComponent(id)}/run`,
    method: "POST",
    signal,
  })).data;
}

export async function deleteJobSearchSchedule(id: string, signal?: AbortSignal) {
  await apiClient.empty({
    path: `/job-search/schedules/${encodeURIComponent(id)}`,
    method: "DELETE",
    signal,
  });
}

export async function fetchAutomationSearchConfig(id: string, signal?: AbortSignal) {
  return (await apiClient.json<JobSearchConfig>({
    path: `/job-search/configs/${encodeURIComponent(id)}`,
    cache: "no-store",
    signal,
  })).data;
}

export async function createAutomationSearchConfig(
  payload: { name: string; filters: Record<string, unknown> },
  signal?: AbortSignal,
) {
  return (await apiClient.json<JobSearchConfig>({
    path: "/job-search/configs",
    method: "POST",
    json: payload,
    signal,
  })).data;
}

export async function patchAutomationSearchConfig(
  id: string,
  payload: { filters: Record<string, unknown> },
  signal?: AbortSignal,
) {
  return (await apiClient.json<JobSearchConfig>({
    path: `/job-search/configs/${encodeURIComponent(id)}`,
    method: "PATCH",
    json: payload,
    signal,
  })).data;
}
