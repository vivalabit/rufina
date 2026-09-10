import { describe, expect, it } from "vitest";

import {
  getParserLabel,
  getSearchIssuesLabel,
  getSearchSourcesLabel,
} from "@/features/job-search/formatting";
import { defaultParserSearchForm } from "@/features/job-search/model/constants";

describe("job-search formatting", () => {
  it("labels aggregator, legacy, and direct-company sources", () => {
    expect(getParserLabel(undefined)).toBe("LinkedIn");
    expect(getParserLabel("indeed")).toBe("Indeed");
    expect(getParserLabel("jobs.ch")).toBe("jobs.ch");
    expect(getParserLabel("sbb")).toBe("SBB CFF FFS");
    expect(getParserLabel("custom_parser")).toBe("custom_parser");
  });

  it("summarizes normalized parser and direct-company selections", () => {
    expect(
      getSearchSourcesLabel({
        ...defaultParserSearchForm,
        parsers: ["linkedin", "indeed", "linkedin"],
        directCompaniesEnabled: true,
        directCompanyIds: ["sbb", "sbb", "swisscom"],
      }),
    ).toBe("LinkedIn + Indeed + Direct companies (2)");
  });
});

 it("distinguishes failed and partial sources without listing healthy companies", () => {
    expect(getSearchIssuesLabel({
      pwc_switzerland: "Invalid catalog",
      helsana: "Parser returned partial results: kept 31 vacancies",
    })).toBe("Failed (1): PwC Switzerland; Partial (1): Helsana");
    expect(getSearchIssuesLabel({})).toBe("");
  });
