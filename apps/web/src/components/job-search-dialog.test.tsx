import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  JobSearchDialog,
  type JobSearchDialogProps,
} from "@/components/job-search-dialog";
import { defaultParserSearchForm } from "@/features/job-search/model/constants";
import { directCompanyCatalog } from "@/lib/direct-company-catalog";

function dialogProps(
  overrides: Partial<JobSearchDialogProps> = {},
): JobSearchDialogProps {
  return {
    form: {
      ...defaultParserSearchForm,
      parsers: ["linkedin"],
      directCompaniesEnabled: true,
      directCompanyIds: ["sbb"],
    },
    activeSource: "linkedin",
    sourceConfigs: [],
    selectedSourceConfigIds: {},
    selectedParserSearchConfigId: "",
    directCompanies: directCompanyCatalog.slice(0, 2),
    newLinkedInProfession: "",
    status: "idle",
    message: "",
    onClose: vi.fn(),
    onActivateSource: vi.fn(),
    onToggleParser: vi.fn(),
    onToggleDirectCompanies: vi.fn(),
    onStartSearch: vi.fn(),
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

describe("JobSearchDialog", () => {
  it("delegates source, close, and start commands", () => {
    const onActivateSource = vi.fn();
    const onToggleParser = vi.fn();
    const onToggleDirectCompanies = vi.fn();
    const onClose = vi.fn();
    const onStartSearch = vi.fn();

    render(
      <JobSearchDialog
        {...dialogProps({
          onActivateSource,
          onToggleParser,
          onToggleDirectCompanies,
          onClose,
          onStartSearch,
        })}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Search vacancies" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Configure LinkedIn" }),
    ).toHaveAttribute("aria-current", "true");
    expect(
      screen.getByRole("button", { name: "Include LinkedIn in search" }),
    ).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(
      screen.getByRole("button", { name: "Configure jobs.ch" }),
    );
    expect(onActivateSource).toHaveBeenCalledWith("jobs_ch");
    fireEvent.click(
      screen.getByRole("button", { name: "Include Indeed in search" }),
    );
    expect(onToggleParser).toHaveBeenCalledWith("indeed");
    fireEvent.click(
      screen.getByRole("button", { name: "Include Direct Companies in search" }),
    );
    expect(onToggleDirectCompanies).toHaveBeenCalledOnce();

    const sourceSummary = screen.getByText("Sources:").closest("p");
    expect(sourceSummary).toHaveTextContent(
      "Sources: LinkedIn + Direct companies (1)",
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Close parser settings" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "Start search" }));
    expect(onStartSearch).toHaveBeenCalledOnce();
  });

  it("shows progress and prevents duplicate search starts while loading", () => {
    const onStartSearch = vi.fn();
    render(
      <JobSearchDialog
        {...dialogProps({
          status: "loading",
          message: "Collecting vacancies…",
          onStartSearch,
        })}
      />,
    );

    expect(screen.getByText("Collecting vacancies…")).toBeInTheDocument();
    const searchButton = screen.getByRole("button", { name: "Searching..." });
    expect(searchButton).toBeDisabled();
    fireEvent.click(searchButton);
    expect(onStartSearch).not.toHaveBeenCalled();
  });
});
