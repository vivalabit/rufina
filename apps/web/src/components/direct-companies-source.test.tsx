import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { DirectCompaniesSource } from "@/components/direct-companies-source";
import type { DirectCompanyDefinition } from "@/lib/direct-company-catalog";

const companies: DirectCompanyDefinition[] = [
  {
    id: "alpha",
    name: "Alpha Labs",
    careersUrl: "https://alpha.example/careers",
  },
  {
    id: "beta",
    name: "Beta Systems",
    careersUrl: "https://jobs.beta.example",
  },
  {
    id: "gamma",
    name: "Gamma AG",
    careersUrl: "https://gamma.example/jobs",
  },
];

function DirectCompaniesHarness() {
  const [selectedCompanyIds, setSelectedCompanyIds] = useState<string[]>([]);
  return (
    <DirectCompaniesSource
      companies={companies}
      selectedCompanyIds={selectedCompanyIds}
      onSelectedCompanyIdsChange={setSelectedCompanyIds}
    />
  );
}

it("filters configured companies and supports selecting or clearing all", () => {
  render(<DirectCompaniesHarness />);

  const search = screen.getByPlaceholderText(
    "Search companies or career pages...",
  );
  fireEvent.change(search, { target: { value: "beta.example" } });
  expect(screen.getByText("Beta Systems")).toBeInTheDocument();
  expect(screen.queryByText("Alpha Labs")).toBeNull();
  expect(screen.queryByText("Gamma AG")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Select all" }));
  expect(screen.getByText("3/3 selected")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Beta Systems/ })).toBeChecked();

  fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
  expect(screen.getByText("0/3 selected")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Beta Systems/ })).not.toBeChecked();
});
