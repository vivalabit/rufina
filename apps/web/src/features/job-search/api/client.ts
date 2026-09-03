import { apiClient } from "@/shared/api/client";

import type {
  JobSearchConfigPayload,
  JobSearchRunPayload,
  JobSourceConfigPayload,
} from "./dto";

export async function fetchSearchConfigs(signal?: AbortSignal) {
  return (await apiClient.json<JobSearchConfigPayload[]>({
    path: "/job-search/configs",
    cache: "no-store",
    signal,
    errorMessage: "Search configs could not be loaded",
  })).data;
}

export async function createSearchConfig(
  input: { name: string; filters: Record<string, unknown> },
  signal?: AbortSignal,
) {
  return (await apiClient.json<JobSearchConfigPayload>({
    path: "/job-search/configs",
    method: "POST",
    json: input,
    signal,
    errorMessage: `Could not import config: ${input.name}`,
  })).data;
}

export async function fetchSourceConfigs(signal?: AbortSignal) {
  return (await apiClient.json<JobSourceConfigPayload[]>({
    path: "/job-search/source-configs",
    cache: "no-store",
    signal,
    errorMessage: "Source configs could not be loaded",
  })).data;
}

export async function saveSourceConfig(
  input: {
    id?: string;
    data: Record<string, unknown>;
  },
  signal?: AbortSignal,
) {
  return (await apiClient.json<JobSourceConfigPayload>({
    path: `/job-search/source-configs${input.id ? `/${encodeURIComponent(input.id)}` : ""}`,
    method: input.id ? "PATCH" : "POST",
    json: input.data,
    signal,
    errorMessage: "Source config could not be saved",
  })).data;
}

export async function runJobSearch(input: Record<string, unknown>, signal?: AbortSignal) {
  return (await apiClient.json<JobSearchRunPayload>({
    path: "/job-search/run",
    method: "POST",
    json: input,
    signal,
    errorMessage: "Vacancy search failed",
    // A provider snapshot can legitimately take several minutes. The caller's
    // AbortSignal still supports cancellation while the backend owns retries.
    timeoutMs: null,
  })).data;
}

export async function fetchJobSearchRuns(limit = 20, signal?: AbortSignal) {
  return (await apiClient.json<JobSearchRunPayload[]>({
    path: "/job-search/runs",
    query: { limit },
    cache: "no-store",
    signal,
    errorMessage: "Search progress could not be loaded",
  })).data;
}
