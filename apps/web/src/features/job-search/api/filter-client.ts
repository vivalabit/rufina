import { apiClient } from "@/shared/api/client";

export type VacancySeniority =
  | "intern"
  | "entry"
  | "junior"
  | "associate"
  | "mid"
  | "senior"
  | "lead"
  | "director"
  | "executive";
export type PostingAgeDays = 1 | 7 | 30;

export type VacancyFilterSettings = {
  schemaVersion: number;
  enabled: boolean;
  seniorityEnabled?: boolean;
  allowedSeniority: VacancySeniority[];
  excludedSeniority: VacancySeniority[];
  postingAgeEnabled?: boolean;
  maxPostingAgeDays?: PostingAgeDays | null;
  technologyStackEnabled?: boolean;
  targetTechnologies: string[];
  excludedTechnologies: string[];
  updatedAt?: string | null;
};

const seniorities = new Set<VacancySeniority>([
  "intern", "entry", "junior", "associate", "mid", "senior", "lead",
  "director", "executive",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringList(value: unknown) {
  return Array.isArray(value)
    ? Array.from(new Set(value.filter((item): item is string => typeof item === "string")
      .map((item) => item.trim().replace(/\s+/g, " ")).filter(Boolean)))
    : [];
}

function seniorityList(value: unknown): VacancySeniority[] {
  return stringList(value).filter(
    (item): item is VacancySeniority => seniorities.has(item as VacancySeniority),
  );
}

export function normalizeVacancyFilterSettings(value: unknown): VacancyFilterSettings {
  const payload = isRecord(value) ? value : {};
  const postingAge = payload.maxPostingAgeDays;
  return {
    schemaVersion: typeof payload.schemaVersion === "number" ? payload.schemaVersion : 1,
    enabled: typeof payload.enabled === "boolean" ? payload.enabled : false,
    seniorityEnabled: typeof payload.seniorityEnabled === "boolean" ? payload.seniorityEnabled : true,
    allowedSeniority: seniorityList(payload.allowedSeniority),
    excludedSeniority: seniorityList(payload.excludedSeniority),
    postingAgeEnabled: typeof payload.postingAgeEnabled === "boolean" ? payload.postingAgeEnabled : false,
    maxPostingAgeDays: postingAge === 1 || postingAge === 7 || postingAge === 30 ? postingAge : 7,
    technologyStackEnabled: typeof payload.technologyStackEnabled === "boolean" ? payload.technologyStackEnabled : true,
    targetTechnologies: stringList(payload.targetTechnologies),
    excludedTechnologies: stringList(payload.excludedTechnologies),
    updatedAt: typeof payload.updatedAt === "string" ? payload.updatedAt : "",
  };
}

export async function fetchVacancyFilterSettings(signal?: AbortSignal) {
  return (await apiClient.json<VacancyFilterSettings>({
    path: "/job-search/filter-settings",
    cache: "no-store",
    signal,
  }, normalizeVacancyFilterSettings)).data;
}

export async function putVacancyFilterSettings(
  settings: Omit<VacancyFilterSettings, "updatedAt">,
  signal?: AbortSignal,
) {
  return (await apiClient.json<VacancyFilterSettings>({
    path: "/job-search/filter-settings",
    method: "PUT",
    json: settings,
    signal,
  }, normalizeVacancyFilterSettings)).data;
}
