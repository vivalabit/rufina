import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  JobSearchConfiguration,
  type JobSearchConfigurationProps,
} from "@/components/job-search-configuration";
import type { JobSourceConfigPayload } from "@/features/job-search/api/dto";
import { defaultParserSearchForm } from "@/features/job-search/model/constants";
import { directCompanyCatalog } from "@/lib/direct-company-catalog";

const sourceConfigs: JobSourceConfigPayload[] = [
  {
    id: "entry-it-linkedin",
    name: "Entry IT · LinkedIn",
    configId: "entry-it",
    source: "linkedin",
    filters: {},
    createdAt: "2026-08-30T10:00:00.000Z",
    updatedAt: "2026-08-30T10:00:00.000Z",
  },
  {
    id: "entry-it-indeed",
    name: "Entry IT · Indeed",
    configId: "entry-it",
    source: "indeed",
    filters: {},
    createdAt: "2026-08-30T10:00:00.000Z",
    updatedAt: "2026-08-30T10:00:00.000Z",
  },
];

function configurationProps(
  overrides: Partial<JobSearchConfigurationProps> = {},
): JobSearchConfigurationProps {
  return {
    form: defaultParserSearchForm,
    activeSource: "linkedin",
    sourceConfigs,
    selectedSourceConfigIds: {},
    selectedParserSearchConfigId: "entry-it",
    directCompanies: directCompanyCatalog.slice(0, 2),
    newLinkedInProfession: "",
    onFormChange: vi.fn(),
    onReset: vi.fn(),
    onSelectSourceConfig: vi.fn(),
    onSaveSourceConfig: vi.fn(),
    onSelectedDirectCompaniesChange: vi.fn(),
    onNewLinkedInProfessionChange: vi.fn(),
    onAddLinkedInProfession: vi.fn(),
    onRemoveLinkedInProfession: vi.fn(),
    ...overrides,
  };
}

describe("JobSearchConfiguration", () => {
  it("delegates LinkedIn config, form, and profession changes", () => {
    const onFormChange = vi.fn();
    const onReset = vi.fn();
    const onSelectSourceConfig = vi.fn();
    const onSaveSourceConfig = vi.fn();
    const onNewLinkedInProfessionChange = vi.fn();
    const onAddLinkedInProfession = vi.fn();
    const onRemoveLinkedInProfession = vi.fn();
    const form = {
      ...defaultParserSearchForm,
      keywords: "Platform Engineer",
      linkedinQueries: [
        {
          keyword: "junior",
          experienceLevels: [],
          jobType: null,
          selectiveSearch: true,
        },
        {
          keyword: "Software Engineer",
          experienceLevels: ["Entry level", "Internship"],
          jobType: null,
          selectiveSearch: true,
        },
      ],
    };

    render(
      <JobSearchConfiguration
        {...configurationProps({
          form,
          selectedSourceConfigIds: {
            linkedin: "entry-it-linkedin",
          },
          newLinkedInProfession: "Security Analyst",
          onFormChange,
          onReset,
          onSelectSourceConfig,
          onSaveSourceConfig,
          onNewLinkedInProfessionChange,
          onAddLinkedInProfession,
          onRemoveLinkedInProfession,
        })}
      />,
    );

    const configSelect = screen.getByRole("combobox", {
      name: "LinkedIn query config",
    });
    expect(configSelect).toHaveValue("entry-it-linkedin");
    expect(screen.getByRole("option", { name: "Entry IT" })).toBeInTheDocument();
    fireEvent.change(configSelect, { target: { value: "" } });
    expect(onSelectSourceConfig).toHaveBeenCalledWith("linkedin", "");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Save LinkedIn query config",
      }),
    );
    expect(onSaveSourceConfig).toHaveBeenCalledWith("linkedin");

    fireEvent.change(
      screen.getByRole("textbox", { name: /^Job title or keywords/ }),
      { target: { value: "Product Engineer" } },
    );
    expect(onFormChange).toHaveBeenCalledWith(
      "keywords",
      "Product Engineer",
    );

    expect(
      screen.getByText(/1 supporting entry-level search term stays active/),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Remove profession Software Engineer",
      }),
    );
    expect(onRemoveLinkedInProfession).toHaveBeenCalledWith(1);

    const professionInput = screen.getByRole("textbox", {
      name: "New LinkedIn profession",
    });
    fireEvent.change(professionInput, {
      target: { value: "Data Engineer" },
    });
    expect(onNewLinkedInProfessionChange).toHaveBeenCalledWith(
      "Data Engineer",
    );
    fireEvent.keyDown(professionInput, { key: "Enter" });
    fireEvent.click(
      screen.getByRole("button", { name: "Add LinkedIn profession" }),
    );
    expect(onAddLinkedInProfession).toHaveBeenCalledTimes(2);

    fireEvent.click(
      screen.getByRole("button", { name: "Reset to defaults" }),
    );
    expect(onReset).toHaveBeenCalledOnce();
  });

  it("delegates direct-company selection and direction changes", () => {
    const onFormChange = vi.fn();
    const onSelectedDirectCompaniesChange = vi.fn();

    render(
      <JobSearchConfiguration
        {...configurationProps({
          activeSource: "direct_companies",
          form: {
            ...defaultParserSearchForm,
            directCompaniesEnabled: true,
            directCompanyIds: ["sbb"],
          },
          onFormChange,
          onSelectedDirectCompaniesChange,
        })}
      />,
    );

    expect(
      screen.queryByRole("combobox", { name: /query config/i }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Swisscom/ }));
    expect(onSelectedDirectCompaniesChange).toHaveBeenCalledWith([
      "sbb",
      "swisscom",
    ]);

    fireEvent.change(
      screen.getByRole("combobox", { name: "Direct company direction" }),
      { target: { value: "design" } },
    );
    expect(onFormChange).toHaveBeenCalledWith(
      "directCompanyDirection",
      "design",
    );
  });
});
