import { describe, expect, it } from "vitest";

import { defaultParserSearchForm } from "@/features/job-search/model/constants";
import {
  directCompanyDirectionFromFilters,
  directCompanySearchFiltersFromForm,
  normalizeDirectCompanyIds,
  normalizeParserIds,
  parserSearchFiltersFromForm,
  parserSearchSourceIds,
  sourceSearchDraftFromFilters,
} from "@/features/job-search/model/form-mappers";

describe("job-search form mappers", () => {
  it("normalizes current and legacy source identifiers", () => {
    expect(
      normalizeParserIds({
        ...defaultParserSearchForm,
        parsers: ["linkedin", "linkedin", "indeed"],
      }),
    ).toEqual(["linkedin", "indeed"]);
    expect(
      normalizeParserIds({
        ...defaultParserSearchForm,
        parser: "jobs_ch",
      } as typeof defaultParserSearchForm & { parser: string }),
    ).toEqual(["jobs_ch"]);
    expect(normalizeDirectCompanyIds([" acme ", { id: "acme" }, { id: "beta" }])).toEqual([
      "acme",
      "beta",
    ]);
  });

  it("combines parser and direct-company sources without duplicates", () => {
    expect(
      parserSearchSourceIds({
        ...defaultParserSearchForm,
        parsers: ["linkedin"],
        directCompaniesEnabled: true,
        directCompanyIds: ["acme", "acme"],
      }),
    ).toEqual(["linkedin", "acme"]);
  });

  it("builds versioned filters while preserving screening settings", () => {
    const filters = parserSearchFiltersFromForm(
      {
        ...defaultParserSearchForm,
        keywords: "  frontend  ",
        location: " Zurich ",
        resultsLimit: "not-a-number",
        linkedinQueries: [
          {
            keyword: " React ",
            experienceLevels: ["Entry level"],
            selectiveSearch: true,
          },
          {
            keyword: "   ",
            experienceLevels: [],
            selectiveSearch: true,
          },
        ],
      },
      {
        schemaVersion: 2,
        search: { custom: "kept", sources: ["linkedin"] },
        screening: { enabled: false, hardRules: ["keep"] },
      },
    );

    expect(filters).toMatchObject({
      schemaVersion: 2,
      search: {
        custom: "kept",
        keywords: "frontend",
        location: "Zurich",
        resultsLimit: 10,
        linkedinQueries: [
          {
            keyword: "React",
            experienceLevels: ["Entry level"],
          },
        ],
      },
      screening: { enabled: false, hardRules: ["keep"] },
    });
    expect((filters.search as Record<string, unknown>).sources).toBeUndefined();
  });

  it("round-trips legacy snake-case source filters", () => {
    const draft = sourceSearchDraftFromFilters(
      {
        experience_level: "Entry level",
        job_type: "Internship",
        results_limit: "17",
        linkedin_queries: [
          {
            keyword: "Engineer",
            experience_levels: ["Internship"],
            selective_search: false,
          },
        ],
        limit_per_input: 9,
      },
      defaultParserSearchForm,
    );

    expect(draft).toMatchObject({
      experienceLevel: "Entry level",
      jobType: "Internship",
      resultsLimit: "17",
      limitPerInput: "9",
      linkedinQueries: [
        {
          keyword: "Engineer",
          experienceLevels: ["Internship"],
          selectiveSearch: false,
        },
      ],
    });
  });

  it("maps direct-company directions to screening target roles", () => {
    const form = {
      ...defaultParserSearchForm,
      directCompanyDirection: "engineering" as const,
      searchName: "  Direct roles  ",
    };
    const filters = directCompanySearchFiltersFromForm(form);

    expect(filters).toMatchObject({
      search: { searchName: "Direct roles", resultsLimit: 1000 },
      screening: { enabled: true, targetRoles: ["Engineering and Technical"] },
    });
    expect(directCompanyDirectionFromFilters(filters)).toBe("engineering");
  });
});
