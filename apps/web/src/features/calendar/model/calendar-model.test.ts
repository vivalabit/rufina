import { describe, expect, it } from "vitest";

import type {
  ApplicationEvent,
  TrackedApplication,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";

import {
  formatCalendarLongDate,
  formatCalendarMonthLabel,
  formatInterviewPreparationPrompt,
} from "../formatting";
import { createCalendarDemoEvents } from "./demo-events";
import {
  filterCalendarEventsByType,
  findCalendarEventApplication,
  getCalendarEventCompany,
  selectCalendarDisplayEvents,
  selectCalendarMonthEvents,
  selectNextCalendarInterview,
  selectUpcomingCalendarEvents,
} from "./selectors";

function event(overrides: Partial<ApplicationEvent> = {}): ApplicationEvent {
  return {
    id: "event-1",
    applicationId: "application-1",
    type: "interview",
    status: "scheduled",
    title: "Interview",
    startsAt: "2026-08-31T10:00:00.000Z",
    durationMinutes: 30,
    timezone: "Europe/Zurich",
    location: "Video call",
    notes: "Bring examples",
    ...overrides,
  };
}

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    company: "Acme",
    title: "Engineer",
    location: "Zurich",
    type: "Full-time",
    salary: "N/A",
    posted: "1h ago",
    experience: "Mid-level",
    department: "Engineering",
    match: 75,
    logo: "company",
    overview: "",
    responsibilities: [],
    requirements: [],
    skills: [],
    salaryAverage: "N/A",
    salaryMin: "N/A",
    salaryMax: "N/A",
    recommendations: [],
    companyInfo: "",
    reviews: [],
    similarJobs: [],
    ...overrides,
  };
}

function application(
  overrides: Partial<TrackedApplication> = {},
): TrackedApplication {
  return {
    id: "application-1",
    job: job(),
    status: "applied",
    appliedAt: "2026-08-01T10:00:00.000Z",
    nextStep: "",
    notes: "",
    documents: [],
    ...overrides,
  };
}

describe("calendar model", () => {
  it("uses demo events only when there are no stored events", () => {
    const stored = [event({ id: "stored" })];
    const demo = [event({ id: "demo" })];

    expect(selectCalendarDisplayEvents(stored, demo)).toBe(stored);
    expect(selectCalendarDisplayEvents([], demo)).toBe(demo);
  });

  it("filters types and visible months without changing event order", () => {
    const source = [
      event({ id: "late", startsAt: "2026-08-20T10:00:00.000Z" }),
      event({ id: "other-type", type: "assessment" }),
      event({ id: "early", startsAt: "2026-08-01T10:00:00.000Z" }),
      event({ id: "other-month", startsAt: "2026-09-01T10:00:00.000Z" }),
    ];

    expect(
      filterCalendarEventsByType(source, "interview").map((item) => item.id),
    ).toEqual(["late", "early", "other-month"]);
    expect(
      selectCalendarMonthEvents(source, new Date(2026, 7, 1)).map(
        (item) => item.id,
      ),
    ).toEqual(["late", "other-type", "early"]);
  });

  it("selects scheduled upcoming events with an explicit clock", () => {
    const nowMs = Date.parse("2026-08-31T09:00:00.000Z");
    const source = [
      event({ id: "third", startsAt: "2026-08-31T12:00:00.000Z" }),
      event({ id: "past", startsAt: "2026-08-31T08:59:59.999Z" }),
      event({ id: "second", startsAt: "2026-08-31T11:00:00.000Z" }),
      event({ id: "completed", status: "completed" }),
      event({ id: "first", startsAt: "2026-08-31T09:00:00.000Z" }),
      event({ id: "fourth", startsAt: "2026-08-31T13:00:00.000Z" }),
    ];

    expect(
      selectUpcomingCalendarEvents(source, nowMs).map((item) => item.id),
    ).toEqual(["first", "second", "third"]);
  });

  it("finds the next interview independently of an active display filter", () => {
    const nowMs = Date.parse("2026-08-31T09:00:00.000Z");
    const displayEvents = [
      event({ id: "assessment", type: "assessment" }),
      event({ id: "later", startsAt: "2026-08-31T12:00:00.000Z" }),
      event({ id: "next", startsAt: "2026-08-31T10:00:00.000Z" }),
    ];

    expect(filterCalendarEventsByType(displayEvents, "assessment")).toHaveLength(1);
    expect(selectNextCalendarInterview(displayEvents, nowMs)?.id).toBe("next");
  });

  it("resolves linked applications and standalone company labels", () => {
    const applications = [application()];
    const linked = event();

    expect(findCalendarEventApplication(applications, linked)?.id).toBe(
      "application-1",
    );
    expect(getCalendarEventCompany(applications, linked)).toBe("Acme");
    expect(
      getCalendarEventCompany(
        [],
        event({ type: "assessment", applicationId: "" }),
      ),
    ).toBe("Assessment");
    expect(
      getCalendarEventCompany(
        [],
        event({ type: "follow_up", applicationId: "", notes: "" }),
      ),
    ).toBe("Reminder");
    expect(
      getCalendarEventCompany(
        [],
        event({ type: "offer_deadline", applicationId: "", notes: "Acme" }),
      ),
    ).toBe("Acme");
  });

  it("creates the unchanged demo schedule with an injected timezone", () => {
    const events = createCalendarDemoEvents(
      new Date(2026, 7, 1),
      "Europe/Zurich",
    );

    expect(events.map((item) => item.id)).toEqual([
      "demo-assessment",
      "demo-interview-wealth",
      "demo-interview-belimo",
      "demo-follow-up",
      "demo-offer",
    ]);
    expect(events.map((item) => new Date(item.startsAt).getDate())).toEqual([
      8, 15, 17, 21, 23,
    ]);
    expect(events.map((item) => item.timezone)).toEqual(
      Array(5).fill("Europe/Zurich"),
    );
  });

  it("formats calendar labels and interview preparation text", () => {
    const linkedApplication = application();
    const interview = event();
    const prompt = formatInterviewPreparationPrompt(
      interview,
      linkedApplication,
      "Prepare me",
    );

    expect(formatCalendarMonthLabel(new Date(2026, 7, 1))).toBe("August 2026");
    expect(formatCalendarLongDate(new Date(2026, 7, 31))).toContain("August");
    expect(prompt).toContain("Prepare me\nInterview: Interview");
    expect(prompt).toContain("Role: Engineer at Acme");
    expect(prompt).toContain("(Europe/Zurich)");
    expect(prompt).toContain("Location: Video call\nNotes: Bring examples");
  });
});
