import {
  defaultParserSearchForm,
  directCompanyDirections,
} from "@/features/job-search/model/constants";
import type {
  DirectCompanyDirection,
  LinkedInDiscoveryQueryDraft,
  ParserId,
  ParserSearchForm,
  SourceSearchDraft,
} from "@/features/job-search/model/types";

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function filterString(
  filters: Record<string, unknown>,
  ...keys: string[]
): string {
  for (const key of keys) {
    if (typeof filters[key] === "string") return filters[key];
  }
  return "";
}

export function filterNumber(
  filters: Record<string, unknown>,
  ...keys: string[]
): number | null {
  for (const key of keys) {
    const value = filters[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && Number.isFinite(Number(value))) {
      return Number(value);
    }
  }
  return null;
}

export function filterBoolean(
  filters: Record<string, unknown>,
  ...keys: string[]
): boolean | null {
  for (const key of keys) {
    if (typeof filters[key] === "boolean") return filters[key];
  }
  return null;
}

export function normalizeDirectCompanyIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];

  return Array.from(
    new Set(
      value.flatMap((item) => {
        const id =
          typeof item === "string"
            ? item.trim()
            : isRecord(item)
              ? filterString(item, "id").trim()
              : "";
        return id ? [id] : [];
      }),
    ),
  );
}

export function normalizeParserIds(form: ParserSearchForm): ParserId[] {
  const parserCandidates = Array.isArray(form.parsers) ? form.parsers : [];
  const legacyParser = (form as ParserSearchForm & { parser?: unknown }).parser;
  const validParsers = parserCandidates.filter(
    (parser): parser is ParserId =>
      parser === "linkedin" || parser === "indeed" || parser === "jobs_ch",
  );
  if (validParsers.length > 0) return Array.from(new Set(validParsers));
  if (
    legacyParser === "linkedin" ||
    legacyParser === "indeed" ||
    legacyParser === "jobs_ch"
  ) {
    return [legacyParser];
  }
  if (form.directCompaniesEnabled) return [];
  return [...defaultParserSearchForm.parsers];
}

export function parserSearchSourceIds(form: ParserSearchForm): string[] {
  return Array.from(
    new Set([
      ...normalizeParserIds(form),
      ...(form.directCompaniesEnabled
        ? normalizeDirectCompanyIds(form.directCompanyIds)
        : []),
    ]),
  );
}

export function isLinkedInProfessionQuery(
  query: LinkedInDiscoveryQueryDraft,
) {
  return query.experienceLevels.length > 0;
}

export function parserSearchFiltersFromForm(
  form: ParserSearchForm,
  currentFilters: Record<string, unknown> = {},
): Record<string, unknown> {
  const linkedinQueries = Array.isArray(form.linkedinQueries)
    ? form.linkedinQueries.flatMap((query) => {
        const keyword = query.keyword.trim();
        return keyword ? [{ ...query, keyword }] : [];
      })
    : [];
  const versioned =
    isRecord(currentFilters.search) || isRecord(currentFilters.screening);
  const currentSearch =
    versioned && isRecord(currentFilters.search)
      ? currentFilters.search
      : versioned
        ? {}
        : currentFilters;
  const currentScreening = isRecord(currentFilters.screening)
    ? currentFilters.screening
    : null;

  return {
    ...(versioned ? currentFilters : {}),
    schemaVersion: 2,
    search: {
      ...currentSearch,
      keywords: form.keywords.trim(),
      location: form.location.trim(),
      remote: form.remote,
      experienceLevel: form.experienceLevel,
      jobType: form.jobType,
      datePosted: form.datePosted,
      resultsLimit: Number.parseInt(form.resultsLimit, 10) || 10,
      country: form.country,
      deduplicate: form.deduplicate,
      ...(linkedinQueries.length > 0
        ? {
            linkedinQueries,
            limitPerInput: Number.parseInt(form.limitPerInput, 10) || 25,
          }
        : {}),
      searchName: form.searchName.trim(),
      folder: form.folder,
      sources: undefined,
      parsers: undefined,
      directCompaniesEnabled: undefined,
      direct_companies_enabled: undefined,
      directCompanyIds: undefined,
      direct_company_ids: undefined,
      directCompanies: undefined,
      direct_companies: undefined,
    },
    screening: currentScreening ?? {
      enabled: true,
      targetRoles: form.keywords.trim() ? [form.keywords.trim()] : [],
      excludedRoles: [],
      allowedSeniority: [],
      excludedSeniority: [],
      hardRules: [],
    },
  };
}

export function directCompanyDirectionFromFilters(
  filters: Record<string, unknown>,
): DirectCompanyDirection {
  const screening = isRecord(filters.screening) ? filters.screening : null;
  const targetRoles = screening?.targetRoles ?? screening?.target_roles;
  if (!Array.isArray(targetRoles)) {
    return defaultParserSearchForm.directCompanyDirection;
  }
  const normalizedRoles = new Set(
    targetRoles.flatMap((role) =>
      typeof role === "string" ? [role.trim().toLocaleLowerCase()] : [],
    ),
  );
  return (
    directCompanyDirections.find(
      (direction) =>
        direction.targetRole &&
        normalizedRoles.has(direction.targetRole.toLocaleLowerCase()),
    )?.id ?? defaultParserSearchForm.directCompanyDirection
  );
}

export function directCompanySearchFiltersFromForm(
  form: ParserSearchForm,
): Record<string, unknown> {
  const direction =
    directCompanyDirections.find(
      (option) => option.id === form.directCompanyDirection,
    ) ?? directCompanyDirections[0];
  const targetRoles = direction.targetRole ? [direction.targetRole] : [];

  return {
    schemaVersion: 2,
    search: {
      keywords: "",
      location: "",
      remote: "Any",
      experienceLevel: "Any",
      jobType: "Any",
      datePosted: "Any time",
      resultsLimit: 1000,
      country: "Any",
      deduplicate: true,
      searchName: form.searchName.trim(),
      folder: form.folder,
    },
    screening: {
      enabled: targetRoles.length > 0,
      targetRoles,
      excludedRoles: [],
      allowedSeniority: [],
      excludedSeniority: [],
      hardRules: [],
    },
  };
}

export function sourceSearchFiltersFromForm(
  form: ParserSearchForm,
): Record<string, unknown> {
  const filters = parserSearchFiltersFromForm(form);
  return isRecord(filters.search) ? filters.search : {};
}

export function sourceSearchDraftFromForm(
  form: ParserSearchForm,
): SourceSearchDraft {
  return {
    keywords: form.keywords,
    location: form.location,
    remote: form.remote,
    experienceLevel: form.experienceLevel,
    jobType: form.jobType,
    datePosted: form.datePosted,
    resultsLimit: form.resultsLimit,
    country: form.country,
    deduplicate: form.deduplicate,
    linkedinQueries: form.linkedinQueries,
    limitPerInput: form.limitPerInput,
  };
}

export function linkedInDiscoveryQueriesFromFilters(
  filters: Record<string, unknown>,
): LinkedInDiscoveryQueryDraft[] {
  const raw = filters.linkedinQueries ?? filters.linkedin_queries;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((value) => {
    if (!isRecord(value) || typeof value.keyword !== "string") return [];
    const rawLevels = value.experienceLevels ?? value.experience_levels;
    return [
      {
        keyword: value.keyword,
        experienceLevels: Array.isArray(rawLevels)
          ? rawLevels.filter(
              (level): level is string => typeof level === "string",
            )
          : [],
        jobType:
          typeof (value.jobType ?? value.job_type) === "string"
            ? String(value.jobType ?? value.job_type)
            : null,
        selectiveSearch:
          typeof (value.selectiveSearch ?? value.selective_search) === "boolean"
            ? Boolean(value.selectiveSearch ?? value.selective_search)
            : true,
      },
    ];
  });
}

export function sourceSearchDraftFromFilters(
  filters: Record<string, unknown>,
  fallback: ParserSearchForm,
): SourceSearchDraft {
  const stringValue = (fallbackValue: string, ...keys: string[]) => {
    for (const key of keys) {
      if (typeof filters[key] === "string") return filters[key];
    }
    return fallbackValue;
  };

  return {
    keywords: stringValue(fallback.keywords, "keywords"),
    location: stringValue(fallback.location, "location"),
    remote: stringValue(fallback.remote, "remote"),
    experienceLevel: stringValue(
      fallback.experienceLevel,
      "experienceLevel",
      "experience_level",
    ),
    jobType: stringValue(fallback.jobType, "jobType", "job_type"),
    datePosted: stringValue(fallback.datePosted, "datePosted", "date_posted"),
    resultsLimit: String(
      filterNumber(filters, "resultsLimit", "results_limit") ??
        (Number.parseInt(fallback.resultsLimit, 10) || 10),
    ),
    country: stringValue(fallback.country, "country"),
    deduplicate: filterBoolean(filters, "deduplicate") ?? fallback.deduplicate,
    linkedinQueries: linkedInDiscoveryQueriesFromFilters(filters),
    limitPerInput: String(
      filterNumber(filters, "limitPerInput", "limit_per_input") ??
        (Number.parseInt(fallback.limitPerInput, 10) || 25),
    ),
  };
}
