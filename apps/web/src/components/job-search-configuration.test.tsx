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
    newProfession: "",
    onFormChange: vi.fn(),
    onReset: vi.fn(),
    onSelectSourceConfig: vi.fn(),
    onSaveSourceConfig: vi.fn(),
    onSelectedDirectCompaniesChange: vi.fn(),
    onNewProfessionChange: vi.fn(),
    onAddProfession: vi.fn(),
    onRemoveProfession: vi.fn(),
    ...overrides,
  };
}

describe("JobSearchConfiguration", () => {
  it("delegates LinkedIn config, form, and profession changes", () => {
    const onFormChange = vi.fn();
    const onReset = vi.fn();
    const onSelectSourceConfig = vi.fn();
    const onSaveSourceConfig = vi.fn();
    const onNewProfessionChange = vi.fn();
    const onAddProfession = vi.fn();
    const onRemoveProfession = vi.fn();
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
          newProfession: "Security Analyst",
          onFormChange,
          onReset,
          onSelectSourceConfig,
          onSaveSourceConfig,
          onNewProfessionChange,
          onAddProfession,
          onRemoveProfession,
        })}
      />,
    );

    const configSelect = screen.getByRole("combobox", {
      name: "LinkedIn query config",
    });
    expect(configSelect).toHaveValue("entry-it-linkedin");
    expect(
      screen.getByRole("option", { name: "Entry IT" }),
    ).toBeInTheDocument();
    fireEvent.change(configSelect, { target: { value: "" } });
    expect(onSelectSourceConfig).toHaveBeenCalledWith("linkedin", "");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Save LinkedIn query config",
      }),
    );
    expect(onSaveSourceConfig).toHaveBeenCalledWith("linkedin");

    expect(
      screen.queryByRole("textbox", { name: /^Job title or keywords/ }),
    ).not.toBeInTheDocument();

    expect(
      screen.getByText(/1 supporting entry-level search term stays active/),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Remove profession Software Engineer",
      }),
    );
    expect(onRemoveProfession).toHaveBeenCalledWith(1);

    const professionInput = screen.getByRole("textbox", {
      name: "New LinkedIn profession",
    });
    fireEvent.change(professionInput, {
      target: { value: "Data Engineer" },
    });
    expect(onNewProfessionChange).toHaveBeenCalledWith("Data Engineer");
    fireEvent.keyDown(professionInput, { key: "Enter" });
    fireEvent.click(
      screen.getByRole("button", { name: "Add LinkedIn profession" }),
    );
    expect(onAddProfession).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(onReset).toHaveBeenCalledOnce();
  });

  it("shows professions for non-LinkedIn parsers", () => {
    const onNewProfessionChange = vi.fn();
    const onAddProfession = vi.fn();
    const onRemoveProfession = vi.fn();

    render(
      <JobSearchConfiguration
        {...configurationProps({
          activeSource: "indeed",
          form: {
            ...defaultParserSearchForm,
            keywords: "Product Engineer OR Data Engineer",
          },
          newProfession: "Security Analyst",
          onNewProfessionChange,
          onAddProfession,
          onRemoveProfession,
        })}
      />,
    );

    expect(screen.queryByText("Job title or keywords")).not.toBeInTheDocument();
    expect(screen.getByText("Product Engineer")).toBeInTheDocument();
    expect(screen.getByText("Data Engineer")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Remove profession Data Engineer" }),
    );
    expect(onRemoveProfession).toHaveBeenCalledWith(1);
    fireEvent.change(
      screen.getByRole("textbox", { name: "New Indeed profession" }),
      { target: { value: "QA Engineer" } },
    );
    expect(onNewProfessionChange).toHaveBeenCalledWith("QA Engineer");
    fireEvent.click(
      screen.getByRole("button", { name: "Add Indeed profession" }),
    );
    expect(onAddProfession).toHaveBeenCalledOnce();
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

  it("explains jobs.ch capabilities without clearing saved unsupported filters", () => {
    const onFormChange = vi.fn();
    render(
      <JobSearchConfiguration
        {...configurationProps({
          activeSource: "jobs_ch",
          form: {
            ...defaultParserSearchForm,
            remote: "Hybrid",
            jobType: "Contract",
            country: "Germany",
            experienceLevel: "Entry level",
          },
          onFormChange,
        })}
      />,
    );

    const remote = screen.getByRole("combobox", { name: /^Remote/ });
    expect(remote).toBeDisabled();
    expect(remote).toHaveValue("Hybrid");
    const jobType = screen.getByRole("combobox", { name: /^Job type/ });
    expect(jobType).toBeDisabled();
    expect(jobType).toHaveValue("Contract");
    const country = screen.getByRole("combobox", { name: /^Country/ });
    expect(country).toHaveValue("Germany");
    expect(screen.getByRole("option", { name: "Germany" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "Switzerland" })).toBeEnabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saved filters are not applied to jobs.ch: Remote: Hybrid; Job type: Contract; Country: Germany.",
    );
    expect(onFormChange).not.toHaveBeenCalled();

    expect(
      screen.getByText("Leave empty to search all jobs.ch locations"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Applied after collection alongside the Vacancy Filter"),
    ).toBeInTheDocument();
    const experience = screen.getByRole("combobox", {
      name: /^Experience level/,
    });
    expect(experience).toBeEnabled();
    fireEvent.change(experience, { target: { value: "Associate" } });
    expect(onFormChange).toHaveBeenCalledWith("experienceLevel", "Associate");
    fireEvent.change(country, { target: { value: "Any" } });
    expect(onFormChange).toHaveBeenCalledWith("country", "Any");
    expect(
      screen.getByRole("combobox", { name: /^Date posted/ }),
    ).toBeEnabled();
  });

  it.each(["linkedin", "indeed"] as const)(
    "keeps %s filters editable when switching from jobs.ch",
    (activeSource) => {
      const props = configurationProps({ activeSource: "jobs_ch" });
      const { rerender } = render(<JobSearchConfiguration {...props} />);

      expect(screen.queryByRole("status")).not.toBeInTheDocument();
      expect(screen.getByRole("combobox", { name: /^Remote/ })).toBeDisabled();
      rerender(
        <JobSearchConfiguration {...props} activeSource={activeSource} />,
      );

      expect(screen.getByRole("combobox", { name: /^Remote/ })).toBeEnabled();
      expect(screen.getByRole("combobox", { name: /^Job type/ })).toBeEnabled();
      expect(screen.getByRole("option", { name: "Germany" })).toBeEnabled();
      expect(
        screen.queryByText(/jobs.ch searches by profession and location/),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText("Leave empty to search worldwide"),
      ).toBeInTheDocument();
    },
  );
});
