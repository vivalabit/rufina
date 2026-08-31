import type { JobSearchConfigPayload } from "@/features/job-search/api/dto";
import { parserSearchConfigFromApi } from "@/features/job-search/api/mappers";
import { defaultParserSearchForm } from "@/features/job-search/model/constants";
import {
  isRecord,
  normalizeDirectCompanyIds,
  normalizeParserIds,
  parserSearchFiltersFromForm,
} from "@/features/job-search/model/form-mappers";
import type {
  ParserSearchConfig,
  ParserSearchForm,
} from "@/features/job-search/model/types";

export function normalizeParserSearchConfigs(configs: ParserSearchConfig[]) {
  const normalizedConfigs = configs
    .filter((config) => config.id && config.name && config.form)
    .map((config) => ({
      ...config,
      form: {
        ...defaultParserSearchForm,
        ...config.form,
        parsers: normalizeParserIds(config.form),
        directCompaniesEnabled:
          config.form.directCompaniesEnabled === true,
        directCompanyIds: normalizeDirectCompanyIds(
          config.form.directCompanyIds ??
            (config.form as ParserSearchForm & { directCompanies?: unknown })
              .directCompanies,
        ),
      },
      filters: isRecord(config.filters)
        ? config.filters
        : parserSearchFiltersFromForm(config.form),
    }));
  const uniqueConfigs = new Map<string, ParserSearchConfig>();

  for (const config of normalizedConfigs) {
    uniqueConfigs.set(config.id, config);
  }

  return Array.from(uniqueConfigs.values());
}

export function hasEquivalentServerSearchConfig(
  legacyConfig: ParserSearchConfig,
  serverConfigs: JobSearchConfigPayload[],
) {
  const legacyFilters = parserSearchFiltersFromForm(legacyConfig.form);
  return serverConfigs.some((serverConfig) => {
    if (serverConfig.name !== legacyConfig.name) return false;
    return (
      JSON.stringify(
        parserSearchFiltersFromForm(
          parserSearchConfigFromApi(serverConfig).form,
        ),
      ) === JSON.stringify(legacyFilters)
    );
  });
}
