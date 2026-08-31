import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { DashboardView } from "@/components/dashboard-view";
import { assistantPrompts } from "@/features/app-shell/model/assistant-prompts";
import { demoJobs } from "@/features/jobs/model/demo-jobs";
import { defaultCandidateProfile } from "@/features/profile/model/defaults";
import type {
  ApplicationEvent,
  TrackedApplication,
} from "@/shared/types/application";

const application: TrackedApplication = {
  id: "application-1",
  job: demoJobs[0],
  status: "applied",
  appliedAt: "2026-08-20T08:00:00.000Z",
  nextStep: "Technical interview",
  notes: "Prepare product-design examples",
  documents: [],
};

const interview: ApplicationEvent = {
  id: "event-1",
  applicationId: application.id,
  type: "interview",
  status: "scheduled",
  title: "Technical interview",
  startsAt: "2026-09-01T09:00:00.000Z",
  durationMinutes: 60,
  timezone: "Europe/Zurich",
  location: "Video call",
  notes: "",
};

function renderDashboardView(
  overrides: Partial<React.ComponentProps<typeof DashboardView>> = {},
) {
  const props: React.ComponentProps<typeof DashboardView> = {
    profile: {
      ...defaultCandidateProfile,
      name: "Alex Morgan",
    },
    jobs: [demoJobs[0]],
    applications: [application],
    events: [],
    isLoading: false,
    onStartSearch: vi.fn(),
    onOpenJobs: vi.fn(),
    onOpenJob: vi.fn(),
    onOpenApplications: vi.fn(),
    onOpenCalendar: vi.fn(),
    onOpenAssistant: vi.fn(),
    ...overrides,
  };

  render(<DashboardView {...props} />);
  return props;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-31T08:00:00.000Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

it("renders dashboard data and preserves parent navigation callbacks", () => {
  const props = renderDashboardView();

  expect(
    screen.getByRole("heading", { name: /Alex/ }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Best Matches" }),
  ).toBeInTheDocument();
  expect(screen.getAllByText(demoJobs[0].title).length).toBeGreaterThan(0);

  fireEvent.click(screen.getByRole("button", { name: "Find opportunities" }));
  fireEvent.keyDown(window, { key: "K", ctrlKey: true });
  expect(props.onStartSearch).toHaveBeenCalledTimes(2);

  fireEvent.click(screen.getByRole("button", { name: "Open" }));
  expect(props.onOpenJob).toHaveBeenCalledWith(demoJobs[0].id);

  fireEvent.click(screen.getByRole("button", { name: /^In Progress/ }));
  expect(props.onOpenApplications).toHaveBeenCalledWith();

  fireEvent.click(screen.getByRole("button", { name: "View all jobs" }));
  expect(props.onOpenJobs).toHaveBeenCalledOnce();

  fireEvent.click(
    screen.getAllByRole("button", { name: /^Open calendar for/ })[0],
  );
  expect(props.onOpenCalendar).toHaveBeenCalledOnce();
});

it("routes upcoming events and assistant actions with application context", () => {
  const props = renderDashboardView({ events: [interview] });

  fireEvent.click(
    screen.getByRole("button", { name: /Technical interview/ }),
  );
  expect(props.onOpenApplications).toHaveBeenCalledWith(application.id);

  fireEvent.click(screen.getByRole("button", { name: "Review" }));
  expect(props.onOpenAssistant).toHaveBeenCalledWith(
    assistantPrompts.prepareInterview,
    "application",
    application.id,
  );

  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  expect(props.onOpenAssistant).toHaveBeenLastCalledWith();
});
