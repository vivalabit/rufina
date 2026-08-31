import { describe, expect, it } from "vitest";

import type {
  ApplicationEvent,
  TrackedApplication,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";

import {
  buildApplicationTimeline,
  filterAndSortApplications,
  getApplicationEventsFor,
  getApplicationStatusCounts,
  getNextUpcomingApplicationEvent,
  getVisibleSelectedApplication,
} from "./selectors";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "static-job-1",
    company: "Example",
    title: "Engineer",
    location: "Zurich",
    type: "Full-time",
    salary: "N/A",
    posted: "1h ago",
    experience: "Mid-level",
    department: "Engineering",
    match: 50,
    logo: "stripe",
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
    nextStep: "Interview",
    notes: "",
    documents: [],
    ...overrides,
  };
}

function event(overrides: Partial<ApplicationEvent> = {}): ApplicationEvent {
  return {
    id: "event-1",
    applicationId: "application-1",
    type: "interview",
    status: "scheduled",
    title: "Interview",
    startsAt: "2026-09-01T10:00:00.000Z",
    durationMinutes: 30,
    timezone: "Europe/Zurich",
    location: "Remote",
    notes: "",
    ...overrides,
  };
}

describe("application selectors", () => {
  it("counts statuses and filters only the supported searchable fields", () => {
    const source = [
      application({ id: "one", job: job({ title: "Backend Engineer" }) }),
      application({
        id: "two",
        status: "interview",
        job: job({ id: "two", company: "Acme" }),
      }),
    ];

    expect(getApplicationStatusCounts(source)).toMatchObject({
      applied: 1,
      interview: 1,
      offer: 0,
    });
    expect(
      filterAndSortApplications(source, {
        query: "ACME",
        status: "interview",
        sortBy: "Date applied",
      }).map((item) => item.id),
    ).toEqual(["two"]);
  });

  it("sorts by match, status, and applied date without mutating input", () => {
    const source = [
      application({
        id: "low",
        status: "interview",
        appliedAt: "invalid",
        job: job({ id: "low", match: 40 }),
      }),
      application({
        id: "high",
        status: "applied",
        appliedAt: "2026-08-02T10:00:00.000Z",
        job: job({ id: "high", match: 90 }),
      }),
    ];

    expect(
      filterAndSortApplications(source, {
        query: "",
        status: "all",
        sortBy: "AI Match",
      }).map((item) => item.id),
    ).toEqual(["high", "low"]);
    expect(
      filterAndSortApplications(source, {
        query: "",
        status: "all",
        sortBy: "Status",
      }).map((item) => item.id),
    ).toEqual(["high", "low"]);
    expect(source.map((item) => item.id)).toEqual(["low", "high"]);
  });

  it("selects the visible fallback and sorts events for one application", () => {
    const first = application({ id: "first" });
    const hidden = application({ id: "hidden" });
    const selected = getVisibleSelectedApplication(hidden, [first]);
    const events = getApplicationEventsFor(
      [
        event({ id: "late", startsAt: "2026-09-02T10:00:00.000Z" }),
        event({ id: "other", applicationId: "other" }),
        event({ id: "early", startsAt: "2026-09-01T10:00:00.000Z" }),
      ],
      "application-1",
    );

    expect(selected?.id).toBe("first");
    expect(events.map((item) => item.id)).toEqual(["early", "late"]);
  });

  it("projects timeline states with the original precedence", () => {
    const now = Date.parse("2026-09-01T09:00:00.000Z");
    const events = [
      event({ id: "next", startsAt: "2026-09-01T10:00:00.000Z" }),
      event({ id: "future", startsAt: "2026-09-02T10:00:00.000Z" }),
      event({ id: "done", status: "completed", startsAt: "2026-08-31T10:00:00.000Z" }),
      event({ id: "rejected", status: "completed", outcome: "negative" }),
      event({ id: "canceled", status: "canceled", outcome: "negative" }),
    ];
    const sortedEvents = getApplicationEventsFor(events, "application-1");
    const next = getNextUpcomingApplicationEvent(sortedEvents, now);
    const timeline = buildApplicationTimeline(application(), sortedEvents, next);
    const states = Object.fromEntries(
      timeline
        .filter((item) => item.event)
        .map((item) => [item.event?.id, item.state]),
    );

    expect(next?.id).toBe("next");
    expect(states).toMatchObject({
      next: "current",
      future: "future",
      done: "done",
      rejected: "rejected",
      canceled: "canceled",
    });
  });
});
