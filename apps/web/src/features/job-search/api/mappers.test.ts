import { describe, expect, it } from "vitest";

import { parserSearchConfigFromApi } from "@/features/job-search/api/mappers";

describe("job-search API mappers", () => {
  it("maps versioned snake-case API filters into the edit form", () => {
    const filters = {
      search: {
        sources: ["linkedin", "unknown", "jobs_ch"],
        direct_company_ids: [{ id: "acme" }, "beta"],
        experience_level: "Entry level",
        job_type: "Full-time",
        date_posted: "Past week",
        results_limit: "30",
        limit_per_input: 12,
        deduplicate: false,
        folder: "saved",
      },
      screening: { target_roles: ["Design"] },
    };
    const config = parserSearchConfigFromApi({
      id: "config-1",
      name: "Entry roles",
      createdAt: "2026-08-01T00:00:00Z",
      updatedAt: "2026-08-31T00:00:00Z",
      filters,
    });

    expect(config.form).toMatchObject({
      parsers: ["linkedin", "jobs_ch"],
      directCompaniesEnabled: true,
      directCompanyIds: ["acme", "beta"],
      directCompanyDirection: "design",
      experienceLevel: "Entry level",
      jobType: "Full-time",
      datePosted: "Past week",
      resultsLimit: "30",
      limitPerInput: "12",
      deduplicate: false,
      searchName: "Entry roles",
      folder: "saved",
    });
    expect(config.filters).toBe(filters);
  });

  it("keeps defaults when optional API fields are absent", () => {
    const config = parserSearchConfigFromApi({
      id: "config-2",
      name: "Empty",
      createdAt: "2026-08-01T00:00:00Z",
      updatedAt: "2026-08-31T00:00:00Z",
      filters: {},
    });

    expect(config.form).toMatchObject({
      parsers: [],
      directCompaniesEnabled: false,
      remote: "Any",
      resultsLimit: "10",
      limitPerInput: "25",
      deduplicate: true,
    });
  });
});
