import { describe, expect, it } from "vitest";

import { defaultParserSearchForm } from "@/features/job-search/model/constants";
import type { ParserSearchConfig } from "@/features/job-search/model/types";

import {
  hasEquivalentServerSearchConfig,
  normalizeParserSearchConfigs,
} from "./migrations";

function config(
  overrides: Partial<ParserSearchConfig> = {},
): ParserSearchConfig {
  return {
    id: "legacy-config",
    name: "Legacy Zurich",
    form: {
      ...defaultParserSearchForm,
      keywords: "Platform Engineer",
      location: "Zurich",
      searchName: "Legacy Zurich",
    },
    filters: {},
    updatedAt: "2026-08-01T10:00:00.000Z",
    ...overrides,
  };
}

describe("job-search browser-storage migrations", () => {
  it("normalizes legacy parser and direct-company aliases", () => {
    const [normalized] = normalizeParserSearchConfigs([
      config({
        form: {
          ...defaultParserSearchForm,
          parser: "jobs_ch",
          directCompaniesEnabled: true,
          directCompanyIds: undefined,
          directCompanies: [" acme ", { id: "acme" }, { id: "beta" }],
        } as typeof defaultParserSearchForm & {
          parser: string;
          directCompanyIds: undefined;
          directCompanies: unknown[];
        },
        filters: null as unknown as Record<string, unknown>,
      }),
    ]);

    expect(normalized.form.parsers).toEqual(["jobs_ch"]);
    expect(normalized.form.directCompanyIds).toEqual(["acme", "beta"]);
    expect(normalized.filters).toMatchObject({ schemaVersion: 2 });
  });

  it("keeps the last valid config for each id", () => {
    const normalized = normalizeParserSearchConfigs([
      config({ name: "First" }),
      config({ name: "Last" }),
      config({ id: "", name: "Invalid" }),
    ]);

    expect(normalized).toHaveLength(1);
    expect(normalized[0].name).toBe("Last");
  });

  it("matches server configs by exact name and serialized migrated filters", () => {
    const legacy = config();
    const serverConfig = {
      id: "server-config",
      name: legacy.name,
      filters: {
        schemaVersion: 2,
        search: {
          keywords: "Platform Engineer",
          location: "Zurich",
          remote: "Any",
          experienceLevel: "Any",
          jobType: "Any",
          datePosted: "Any time",
          resultsLimit: 10,
          country: "Any",
          deduplicate: true,
          searchName: "Legacy Zurich",
          folder: "",
        },
        screening: {
          enabled: true,
          targetRoles: ["Platform Engineer"],
          excludedRoles: [],
          allowedSeniority: [],
          excludedSeniority: [],
          hardRules: [],
        },
      },
      createdAt: "2026-08-01T10:00:00.000Z",
      updatedAt: "2026-08-01T10:00:00.000Z",
    };

    expect(hasEquivalentServerSearchConfig(legacy, [serverConfig])).toBe(true);
    expect(
      hasEquivalentServerSearchConfig(legacy, [
        { ...serverConfig, name: "legacy zurich" },
      ]),
    ).toBe(false);
  });
});
