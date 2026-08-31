import type { JobSourceConfigPayload } from "@/features/job-search/api/dto";
import { defaultParserSearchForm } from "@/features/job-search/model/constants";
import { sourceSearchDraftFromFilters } from "@/features/job-search/model/form-mappers";
import type { ParserSearchConfig } from "@/features/job-search/model/types";

export function getSourceSearchConfigLabel(config: JobSourceConfigPayload) {
  return (
    config.name
      .replace(/\s*·\s*(?:LinkedIn|Indeed|jobs(?:\.|_)?ch)$/i, "")
      .trim() || config.name
  );
}

export function getDefaultLinkedInSearchSelection(
  configs: ParserSearchConfig[],
  sourceConfigs: JobSourceConfigPayload[],
) {
  const sourceConfig =
    sourceConfigs.find(
      (config) =>
        config.source === "linkedin" && config.id === "entry-it-linkedin",
    ) ??
    sourceConfigs.find(
      (config) =>
        config.source === "linkedin" &&
        getSourceSearchConfigLabel(config).toLowerCase() === "entry it",
    );
  if (!sourceConfig) return null;

  const commonConfig = configs.find(
    (config) => config.id === sourceConfig.configId,
  );
  const fallback = commonConfig?.form ?? defaultParserSearchForm;
  const draft = sourceSearchDraftFromFilters(sourceConfig.filters, fallback);

  return {
    commonConfigId: sourceConfig.configId,
    sourceConfigId: sourceConfig.id,
    draft,
    form: {
      ...defaultParserSearchForm,
      ...fallback,
      ...draft,
      parsers: [],
      directCompaniesEnabled: false,
      directCompanyIds: [],
      searchName:
        commonConfig?.name ?? getSourceSearchConfigLabel(sourceConfig),
    },
  };
}
