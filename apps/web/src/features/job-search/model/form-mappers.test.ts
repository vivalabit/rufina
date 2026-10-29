import { describe, expect, it } from "vitest";

import { defaultParserSearchForm } from "@/features/job-search/model/constants";
import {
  directCompanyDirectionFromFilters,
  directCompanySearchFiltersFromForm,
  directCompanySpecializationsFromFilters,
  keywordsFromProfessions,
  normalizeDirectCompanyIds,
  normalizeDirectCompanySpecializations,
  normalizeParserIds,
  parserSearchFiltersFromForm,
  parserSearchSourceIds,
  professionsFromKeywords,
  sourceSearchDraftFromFilters,
} from "@/features/job-search/model/form-mappers";

describe("job-search form mappers", () => {
  it("converts keyword expressions to profession lists and back", () => {
    expect(
      professionsFromKeywords(
        "Product Engineer OR Data Engineer or product engineer",
      ),
    ).toEqual(["Product Engineer", "Data Engineer"]);
    expect(keywordsFromProfessions(["Product Engineer", "Data Engineer"])).toBe(
      "Product Engineer OR Data Engineer",
    );
  });

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
    expect(
      normalizeDirectCompanyIds([" acme ", { id: "acme" }, { id: "beta" }]),
    ).toEqual(["acme", "beta"]);
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

  it("keeps broad direction separate from the selected specializations", () => {
    const filters = directCompanySearchFiltersFromForm({
      ...defaultParserSearchForm,
      directCompanySpecializations: ["Backend", "Frontend", "backend"],
    });

    expect(filters.screening).toMatchObject({
      enabled: true,
      targetRoles: ["Information Technology"],
      targetSpecializations: ["Backend", "Frontend"],
    });
    expect(directCompanyDirectionFromFilters(filters)).toBe("information_technology");
    expect(directCompanySpecializationsFromFilters(filters)).toEqual(["Backend", "Frontend"]);
  });

  it("round-trips all directions and enables a specialization-only search", () => {
    const filters = directCompanySearchFiltersFromForm({
      ...defaultParserSearchForm,
      directCompanyDirection: "all",
      directCompanySpecializations: ["Technical Writer"],
    });

    expect(filters.screening).toMatchObject({
      enabled: true,
      targetRoles: [],
      targetSpecializations: ["Technical Writer"],
    });
    expect(directCompanyDirectionFromFilters(filters)).toBe("all");
    expect(directCompanyDirectionFromFilters({})).toBe("information_technology");
  });

  it("preserves legacy broad-direction filters without a specialization restriction", () => {
    const filters = directCompanySearchFiltersFromForm(defaultParserSearchForm);
    expect(filters.screening).not.toHaveProperty("targetSpecializations");
    expect(directCompanySpecializationsFromFilters(filters)).toEqual([]);
    expect(directCompanySpecializationsFromFilters({
      screening: { target_specializations: [" Backend ", "backend", "Data   Engineering"] },
    })).toEqual(["Backend", "Data Engineering"]);
  });

  it("normalizes custom specializations within the API limits", () => {
    expect(normalizeDirectCompanySpecializations([" ", 5, "x".repeat(161), "  Tax ", "tax"]))
      .toEqual(["Tax"]);
    expect(normalizeDirectCompanySpecializations(
      Array.from({ length: 51 }, (_, index) => `Profession ${index}`),
    )).toHaveLength(50);
  });
});
