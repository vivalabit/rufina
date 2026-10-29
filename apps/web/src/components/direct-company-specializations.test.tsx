import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DirectCompanySpecializations } from "@/components/direct-company-specializations";
import type { DirectCompanyDirection } from "@/features/job-search/model/types";

function Picker({
  initial = [],
  direction = "information_technology",
}: {
  initial?: string[];
  direction?: DirectCompanyDirection;
}) {
  const [selected, setSelected] = useState(initial);
  return (
    <DirectCompanySpecializations
      direction={direction}
      selected={selected}
      onChange={setSelected}
    />
  );
}

describe("DirectCompanySpecializations", () => {
  it("selects multiple professions and clears the restriction", () => {
    render(<Picker />);
    const backend = screen.getByRole("button", { name: "Backend" });
    const frontend = screen.getByRole("button", { name: "Frontend" });
    fireEvent.click(backend);
    fireEvent.click(frontend);
    expect(backend).toHaveAttribute("aria-pressed", "true");
    expect(frontend).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    fireEvent.click(backend);
    expect(backend).toHaveAttribute("aria-pressed", "false");
    expect(frontend).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(
      screen.getByRole("button", { name: "Clear specializations" }),
    );
    expect(frontend).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByRole("button", { name: "Clear specializations" }),
    ).toBeDisabled();
  });

  it("adds a custom profession, normalizes whitespace, and prevents duplicates", () => {
    render(<Picker direction="all" />);
    const input = screen.getByRole("textbox", {
      name: "Custom direct company specialization",
    });
    const add = screen.getByRole("button", { name: "Add specialization" });
    expect(add).toBeDisabled();
    fireEvent.change(input, { target: { value: "  Technical   Writer  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(
      screen.getByRole("button", { name: "Technical Writer" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(input).toHaveValue("");
    fireEvent.change(input, { target: { value: "technical writer" } });
    expect(add).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Technical Writer" }));
    expect(add).toBeEnabled();
  });

  it("enforces API limits while allowing selected professions to be removed", () => {
    const initial = Array.from(
      { length: 50 },
      (_, index) => `Profession ${index}`,
    );
    render(<Picker initial={initial} />);
    const input = screen.getByRole("textbox", {
      name: "Custom direct company specialization",
    });
    expect(input).toBeDisabled();
    expect(screen.getByRole("button", { name: "Backend" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "up to 50 specializations",
    );
    fireEvent.click(screen.getByRole("button", { name: "Profession 0" }));
    expect(input).toBeEnabled();
    expect(input).toHaveAttribute("maxlength", "160");
    fireEvent.change(input, { target: { value: "x".repeat(161) } });
    expect(
      screen.getByRole("button", { name: "Add specialization" }),
    ).toBeDisabled();
  });

  it("offers presets for other directions", () => {
    render(<Picker direction="finance_accounting" />);
    expect(
      screen.getByRole("button", { name: "Accounting" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Backend" }),
    ).not.toBeInTheDocument();
  });
});
