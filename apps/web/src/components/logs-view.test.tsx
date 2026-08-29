import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { LogsView, type AppLogEntry } from "@/components/logs-view";

const logs: AppLogEntry[] = [
  {
    id: "error-1",
    timestamp: "2026-08-29T08:15:10.000Z",
    level: "error",
    area: "Applications",
    message: "Application could not be saved",
    details: "Request failed with status 503",
  },
  {
    id: "warning-1",
    timestamp: "2026-08-29T08:14:10.000Z",
    level: "warning",
    area: "Vacancy search",
    message: "Search completed with source warnings",
  },
  {
    id: "success-1",
    timestamp: "2026-08-28T18:12:10.000Z",
    level: "success",
    area: "AI Match",
    message: "AI analysis completed",
    details: "Score: 89%",
  },
  {
    id: "info-1",
    timestamp: "2026-08-28T18:10:10.000Z",
    level: "info",
    area: "Settings",
    message: "Logs view enabled",
  },
];

it("filters activity by severity, area, and searchable details", () => {
  render(<LogsView logs={logs} onClear={vi.fn()} />);

  expect(screen.getByRole("heading", { name: "Activity & logs" })).toBeInTheDocument();
  expect(screen.getByText("4 of 4 events")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Errors\s*1/ }));
  expect(screen.getByText("Application could not be saved")).toBeInTheDocument();
  expect(screen.queryByText("AI analysis completed")).not.toBeInTheDocument();
  expect(screen.getByText("1 of 4 events")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Errors\s*1/ }));
  fireEvent.change(screen.getByRole("searchbox", { name: "Search activity" }), {
    target: { value: "Score: 89" },
  });
  expect(screen.getByText("AI analysis completed")).toBeInTheDocument();
  expect(screen.queryByText("Application could not be saved")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Clear activity search" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Filter activity area" }), {
    target: { value: "Vacancy search" },
  });
  expect(screen.getByText("Search completed with source warnings")).toBeInTheDocument();
  expect(screen.queryByText("Logs view enabled")).not.toBeInTheDocument();
});

it("keeps technical details collapsed and delegates clearing the log", () => {
  const onClear = vi.fn();
  render(<LogsView logs={logs} onClear={onClear} />);

  const details = screen.getAllByText("View details")[0].closest("details");
  expect(details).not.toBeNull();
  expect(details).not.toHaveAttribute("open");
  fireEvent.click(screen.getAllByText("View details")[0]);
  expect(details).toHaveAttribute("open");

  fireEvent.click(screen.getByRole("button", { name: "Clear logs" }));
  expect(onClear).toHaveBeenCalledOnce();
});

it("shows a dedicated empty state", () => {
  render(<LogsView logs={[]} onClear={vi.fn()} />);

  expect(screen.getByRole("heading", { name: "No activity yet" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Clear logs" })).toBeDisabled();
});
