import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SearchHistoryDialog } from "./search-history-dialog";
import {
  fetchSearchHistory,
  fetchSearchReport,
  type SearchHistoryEntry,
  type SearchSourceResult,
} from "@/features/job-search/api/history-client";

vi.mock("@/features/job-search/api/history-client", () => ({
  fetchSearchHistory: vi.fn(),
  fetchSearchReport: vi.fn(),
}));

const source: SearchSourceResult = {
  source: "linkedin",
  status: "completed",
  received: 3,
  firstSeen: 2,
  updated: 0,
  observed: 1,
  added: 1,
  known: 1,
  duplicate: 0,
  filtered: 1,
  uncertain: 0,
  error: 0,
  pending: 0,
  missing: null,
  fullCatalog: false,
  attempts: 1,
  durationSeconds: 12,
  warnings: [],
  errorMessage: null,
};
const entry: SearchHistoryEntry = {
  id: "session-1",
  runs: [
    {
      id: "run-1",
      sessionId: "session-1",
      reportVersion: 1,
      configSnapshot: {
        name: "Backend Switzerland",
        filters: { search: { location: "Zurich" } },
      },
      runType: "manual",
      sources: ["linkedin"],
      status: "completed",
      jobsFound: 3,
      jobsAlreadyKnown: 1,
      jobsDiscoveredNew: 2,
      jobsDiscoveredUpdated: 0,
      jobsAlreadyObserved: 1,
      jobsScreened: 2,
      jobsPassed: 1,
      jobsRejected: 1,
      jobsUncertain: 0,
      jobsAdded: 1,
      jobsAnalyzed: 0,
      screeningErrors: 0,
      jobsScreeningAiCalls: 1,
      sourceErrors: {},
      startedAt: "2026-10-29T09:00:00Z",
      completedAt: "2026-10-29T09:01:00Z",
      report: {
        version: 1,
        sources: [source],
        vacancies: [
          {
            jobId: "sales-1",
            source: "linkedin",
            title: "Sales Manager",
            company: "Example",
            url: "https://example.test/jobs/1",
            outcome: "filtered",
            discovery: "new",
            reason: "The role does not match the selected backend roles.",
            reasonCode: "excluded_role",
          },
        ],
      },
    },
  ],
};

beforeEach(() => {
  vi.mocked(fetchSearchHistory)
    .mockReset()
    .mockResolvedValue({ items: [entry], nextOffset: null });
  vi.mocked(fetchSearchReport).mockReset().mockResolvedValue(entry);
});

it("opens a report, drills into source outcomes and shows saved search settings", async () => {
  render(<SearchHistoryDialog onClose={vi.fn()} />);
  fireEvent.click(
    await screen.findByRole("button", { name: /Backend Switzerland/ }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "LinkedIn: Filtered out 1" }),
  );
  expect(screen.getByRole("tab", { name: "Vacancies" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByLabelText("Vacancy outcome")).toHaveValue("filtered");
  expect(
    screen.getByText("The role does not match the selected backend roles."),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Sales Manager" })).toHaveAttribute(
    "href",
    "https://example.test/jobs/1",
  );
  fireEvent.click(screen.getByRole("tab", { name: "Search settings" }));
  expect(screen.getByText("Zurich")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Search history" }));
  expect(
    await screen.findByRole("button", { name: /Backend Switzerland/ }),
  ).toBeInTheDocument();
});

it("shows legacy summaries without inventing per-source zero counts", async () => {
  vi.mocked(fetchSearchReport).mockResolvedValue({
    ...entry,
    runs: [{ ...entry.runs[0], reportVersion: null, report: null }],
  });
  render(
    <SearchHistoryDialog initialSessionId="session-1" onClose={vi.fn()} />,
  );
  expect(
    await screen.findByText(/were not collected for older searches/),
  ).toBeInTheDocument();
  expect(screen.getByText("Detailed counts unavailable")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Vacancies" }));
  expect(
    screen.getByText("Vacancy details were not collected for this search."),
  ).toBeInTheDocument();
  expect(fetchSearchHistory).not.toHaveBeenCalled();
});

it("retries failed loads and passes pagination and filters to the server", async () => {
  vi.mocked(fetchSearchHistory)
    .mockRejectedValueOnce(new Error("Server unavailable"))
    .mockResolvedValue({ items: [entry], nextOffset: 25 });
  render(<SearchHistoryDialog onClose={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
  await screen.findByRole("button", { name: /Backend Switzerland/ });
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() =>
    expect(fetchSearchHistory).toHaveBeenLastCalledWith(
      25,
      expect.any(Object),
      expect.any(AbortSignal),
    ),
  );
  fireEvent.change(screen.getByLabelText("History source"), {
    target: { value: "jobs_ch" },
  });
  await waitFor(() =>
    expect(fetchSearchHistory).toHaveBeenLastCalledWith(
      0,
      expect.objectContaining({ source: "jobs_ch" }),
      expect.any(AbortSignal),
    ),
  );
});

it("handles Escape and restores focus and body scrolling when closed", async () => {
  const onClose = vi.fn();
  const trigger = document.createElement("button");
  document.body.appendChild(trigger);
  trigger.focus();
  const { unmount } = render(<SearchHistoryDialog onClose={onClose} />);
  const dialog = screen.getByRole("dialog");
  expect(
    within(dialog).getByRole("button", { name: "Close search history" }),
  ).toHaveFocus();
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
  unmount();
  expect(trigger).toHaveFocus();
  expect(document.body.style.overflow).toBe("");
  trigger.remove();
});

it("opens a retained Jobs card from a vacancy result", async () => {
  const onOpenJob = vi.fn();
  render(
    <SearchHistoryDialog
      initialSessionId="session-1"
      onClose={vi.fn()}
      availableJobIds={new Set(["sales-1"])}
      onOpenJob={onOpenJob}
    />,
  );
  fireEvent.click(await screen.findByRole("tab", { name: "Vacancies" }));
  fireEvent.click(screen.getByRole("button", { name: "Open in Jobs" }));
  expect(onOpenJob).toHaveBeenCalledWith("sales-1");
});
