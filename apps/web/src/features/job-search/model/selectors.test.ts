import { describe, expect, it } from "vitest";

import type { JobSourceConfigPayload } from "@/features/job-search/api/dto";
import { defaultParserSearchForm } from "@/features/job-search/model/constants";
import {
  getDefaultLinkedInSearchSelection,
  getSourceSearchConfigLabel,
} from "@/features/job-search/model/selectors";
import type { ParserSearchConfig } from "@/features/job-search/model/types";

function sourceConfig(
  overrides: Partial<JobSourceConfigPayload> = {},
): JobSourceConfigPayload {
  return {
    id: "entry-it-linkedin",
    name: "Entry IT · LinkedIn",
    configId: "entry-it",
    source: "linkedin",
    filters: { keywords: "Developer", results_limit: 15 },
    createdAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-08-31T00:00:00Z",
    ...overrides,
  };
}

describe("job-search selectors", () => {
  it("removes a source suffix from display labels", () => {
    expect(getSourceSearchConfigLabel(sourceConfig())).toBe("Entry IT");
    expect(
      getSourceSearchConfigLabel(sourceConfig({ name: "Entry IT · jobs_ch" })),
    ).toBe("Entry IT");
  });

  it("selects the canonical LinkedIn source configuration", () => {
    const commonConfig: ParserSearchConfig = {
      id: "entry-it",
      name: "Entry IT",
      form: {
        ...defaultParserSearchForm,
        location: "Zurich",
        parsers: ["indeed"],
      },
      filters: {},
      updatedAt: "2026-08-31T00:00:00Z",
    };

    const selection = getDefaultLinkedInSearchSelection(
      [commonConfig],
      [sourceConfig()],
    );

    expect(selection).toMatchObject({
      commonConfigId: "entry-it",
      sourceConfigId: "entry-it-linkedin",
      draft: { keywords: "Developer", resultsLimit: "15", location: "Zurich" },
      form: {
        parsers: [],
        directCompaniesEnabled: false,
        directCompanyIds: [],
        searchName: "Entry IT",
      },
    });
  });

  it("returns null when there is no LinkedIn default", () => {
    expect(
      getDefaultLinkedInSearchSelection([], [sourceConfig({ source: "indeed" })]),
    ).toBeNull();
  });
});
