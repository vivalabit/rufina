import type { JobSearchConfigPayload } from "@/features/job-search/api/dto";
import { defaultParserSearchForm } from "@/features/job-search/model/constants";
import {
  directCompanyDirectionFromFilters,
  filterBoolean,
  filterNumber,
  filterString,
  isRecord,
  linkedInDiscoveryQueriesFromFilters,
  normalizeDirectCompanyIds,
} from "@/features/job-search/model/form-mappers";
import type {
  ParserId,
  ParserSearchConfig,
} from "@/features/job-search/model/types";

export function parserSearchConfigFromApi(
  config: JobSearchConfigPayload,
): ParserSearchConfig {
  const filters = config.filters;
  const searchFilters = isRecord(filters.search) ? filters.search : filters;
  const sources = Array.isArray(searchFilters.sources)
    ? searchFilters.sources.filter(
        (source): source is ParserId =>
          source === "linkedin" ||
          source === "indeed" ||
          source === "jobs_ch",
      )
    : [];
  const directCompanyIds = normalizeDirectCompanyIds(
    searchFilters.directCompanyIds ??
      searchFilters.direct_company_ids ??
      searchFilters.directCompanies ??
      searchFilters.direct_companies,
  );
  const directCompaniesEnabled =
    filterBoolean(
      searchFilters,
      "directCompaniesEnabled",
      "direct_companies_enabled",
    ) ?? directCompanyIds.length > 0;

  return {
    id: config.id,
    name: config.name,
    filters,
    updatedAt: config.updatedAt,
    form: {
      ...defaultParserSearchForm,
      parsers:
        sources.length > 0 || directCompaniesEnabled
          ? sources
          : [...defaultParserSearchForm.parsers],
      directCompaniesEnabled,
      directCompanyIds,
      directCompanyDirection: directCompanyDirectionFromFilters(filters),
      keywords: filterString(searchFilters, "keywords"),
      location: filterString(searchFilters, "location"),
      remote:
        filterString(searchFilters, "remote") || defaultParserSearchForm.remote,
      experienceLevel:
        filterString(searchFilters, "experienceLevel", "experience_level") ||
        defaultParserSearchForm.experienceLevel,
      jobType:
        filterString(searchFilters, "jobType", "job_type") ||
        defaultParserSearchForm.jobType,
      datePosted:
        filterString(searchFilters, "datePosted", "date_posted") ||
        defaultParserSearchForm.datePosted,
      resultsLimit: String(
        filterNumber(searchFilters, "resultsLimit", "results_limit") ?? 10,
      ),
      country:
        filterString(searchFilters, "country") || defaultParserSearchForm.country,
      deduplicate:
        filterBoolean(searchFilters, "deduplicate") ??
        defaultParserSearchForm.deduplicate,
      linkedinQueries: linkedInDiscoveryQueriesFromFilters(searchFilters),
      limitPerInput: String(
        filterNumber(searchFilters, "limitPerInput", "limit_per_input") ?? 25,
      ),
      searchName: config.name,
      folder: filterString(searchFilters, "folder"),
    },
  };
}
