import { apiClient } from "@/shared/api/client";
import type { JobSearchRunPayload } from "./dto";

export type VacancyOutcome =
  | "added"
  | "known"
  | "duplicate"
  | "filtered"
  | "uncertain"
  | "error"
  | "pending"
  | "missing";
export type SearchVacancyResult = {
  jobId: string | null;
  source: string;
  title: string;
  company: string;
  url: string;
  outcome: VacancyOutcome;
  discovery: "new" | "updated" | "observed" | null;
  reason: string;
  reasonCode?: string;
};
export type SearchSourceResult = Record<
  Exclude<VacancyOutcome, "missing">,
  number
> & {
  source: string;
  status: string;
  received: number | null;
  firstSeen: number;
  updated: number;
  observed: number;
  missing: number | null;
  fullCatalog: boolean;
  attempts: number | null;
  durationSeconds: number | null;
  warnings: string[];
  errorMessage: string | null;
};
export type SearchRunReport = {
  version: number;
  detailsRemoved?: boolean;
  sources: SearchSourceResult[];
  vacancies: SearchVacancyResult[];
};
export type SearchHistoryEntry = {
  id: string;
  runs: (JobSearchRunPayload & { report?: SearchRunReport | null })[];
};
export type SearchHistoryPage = {
  items: SearchHistoryEntry[];
  nextOffset: number | null;
};
export type SearchHistoryFilters = {
  query: string;
  source: string;
  runType: string;
  since: string;
  status: string;
};

export async function fetchSearchHistory(
  offset: number,
  filters: SearchHistoryFilters,
  signal?: AbortSignal,
) {
  return (
    await apiClient.json<SearchHistoryPage>({
      path: "/job-search/history",
      query: {
        offset,
        limit: 25,
        ...Object.fromEntries(
          Object.entries(filters).filter(([, value]) => value),
        ),
      },
      signal,
      cache: "no-store",
      errorMessage: "Search history could not be loaded",
    })
  ).data;
}

export async function fetchSearchReport(id: string, signal?: AbortSignal) {
  return (
    await apiClient.json<SearchHistoryEntry>({
      path: `/job-search/history/${encodeURIComponent(id)}`,
      signal,
      cache: "no-store",
      errorMessage: "Search report could not be loaded",
    })
  ).data;
}
