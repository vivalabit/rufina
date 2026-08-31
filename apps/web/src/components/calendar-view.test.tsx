import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CalendarView } from "@/components/calendar-view";
import { demoJobs } from "@/features/jobs/model/demo-jobs";
import type {
  ApplicationEvent,
  TrackedApplication,
} from "@/shared/types/application";

const application: TrackedApplication = {
  id: "application-1",
  job: demoJobs[0],
  status: "interview",
  appliedAt: "2026-08-20T08:00:00.000Z",
  nextStep: "Technical interview",
  notes: "",
  documents: [],
};

const interview: ApplicationEvent = {
  id: "event-1",
  applicationId: application.id,
  type: "interview",
  status: "scheduled",
  title: "Technical interview",
  startsAt: new Date(2026, 7, 31, 14).toISOString(),
  durationMinutes: 60,
  timezone: "Europe/Zurich",
  location: "Google Meet",
  notes: "Prepare portfolio examples",
};

function renderCalendarView(
  overrides: Partial<React.ComponentProps<typeof CalendarView>> = {},
) {
  const props: React.ComponentProps<typeof CalendarView> = {
    applications: [application],
    events: [interview],
    demoMode: false,
    onOpenAssistant: vi.fn(),
    onSaveEvent: vi.fn(),
    onDeleteEvent: vi.fn(),
    ...overrides,
  };

  render(<CalendarView {...props} />);
  return props;
}

describe("CalendarView", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 7, 31, 8, 15));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the current month and delegates interview preparation", () => {
    const props = renderCalendarView();

    expect(
      screen.getByRole("heading", { name: "Calendar" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "August 2026" })).toBeInTheDocument();
    expect(screen.getAllByText(interview.title).length).toBeGreaterThan(0);

    fireEvent.click(
      screen.getByTitle(`Prepare for ${interview.title}`),
    );

    expect(props.onOpenAssistant).toHaveBeenCalledWith(
      expect.stringContaining(`Interview: ${interview.title}`),
      application.id,
    );
    expect(props.onOpenAssistant).toHaveBeenCalledWith(
      expect.stringContaining(
        `Role: ${application.job.title} at ${application.job.company}`,
      ),
      application.id,
    );
  });

  it("edits an existing event without losing its identity or application", () => {
    const props = renderCalendarView();

    fireEvent.click(screen.getAllByText(interview.title)[0]);
    expect(
      screen.getByRole("heading", { name: "Edit event" }),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Event title" }), {
      target: { value: "Updated technical interview" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "Location or link" }),
      { target: { value: "  Zurich office  " } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save event" }));

    expect(props.onSaveEvent).toHaveBeenCalledOnce();
    expect(props.onSaveEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        id: interview.id,
        applicationId: application.id,
        type: interview.type,
        title: "Updated technical interview",
        startsAt: interview.startsAt,
        durationMinutes: interview.durationMinutes,
        timezone: interview.timezone,
        location: "Zurich office",
      }),
    );
    expect(
      screen.queryByRole("heading", { name: "Edit event" }),
    ).not.toBeInTheDocument();
  });
});
