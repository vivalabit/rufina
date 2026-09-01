import { requestJson } from "@/lib/api-client";
import { apiBaseUrl } from "@/shared/api/config";

import type {
  JobSearchConfigPayload,
  JobSearchRunPayload,
  JobSourceConfigPayload,
} from "./dto";

export async function fetchSearchConfigs(signal?: AbortSignal) {
  return (await requestJson<JobSearchConfigPayload[]>(
    `${apiBaseUrl}/job-search/configs`,
    { cache: "no-store", signal },
    { errorMessage: "Search configs could not be loaded" },
  )).data;
}

export async function createSearchConfig(
  input: { name: string; filters: Record<string, unknown> },
  signal?: AbortSignal,
) {
  return (await requestJson<JobSearchConfigPayload>(
    `${apiBaseUrl}/job-search/configs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
      signal,
    },
    { errorMessage: `Could not import config: ${input.name}` },
  )).data;
}

export async function fetchSourceConfigs(signal?: AbortSignal) {
  return (await requestJson<JobSourceConfigPayload[]>(
    `${apiBaseUrl}/job-search/source-configs`,
    { cache: "no-store", signal },
    { errorMessage: "Source configs could not be loaded" },
  )).data;
}

export async function saveSourceConfig(
  input: {
    id?: string;
    data: Record<string, unknown>;
  },
  signal?: AbortSignal,
) {
  return (await requestJson<JobSourceConfigPayload>(
    `${apiBaseUrl}/job-search/source-configs${input.id ? `/${encodeURIComponent(input.id)}` : ""}`,
    {
      method: input.id ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input.data),
      signal,
    },
    { errorMessage: "Source config could not be saved" },
  )).data;
}

export async function runJobSearch(input: Record<string, unknown>, signal?: AbortSignal) {
  return (await requestJson<JobSearchRunPayload>(
    `${apiBaseUrl}/job-search/run`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
      signal,
    },
    { errorMessage: "Vacancy search failed" },
  )).data;
}

export async function fetchJobSearchRuns(limit = 20, signal?: AbortSignal) {
  return (await requestJson<JobSearchRunPayload[]>(
    `${apiBaseUrl}/job-search/runs?limit=${limit}`,
    { cache: "no-store", signal },
    { errorMessage: "Search progress could not be loaded" },
  )).data;
}
