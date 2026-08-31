import { describe, expect, it } from "vitest";

import { getCalendarDateKey } from "@/features/calendar/model/date-grid";
import type {
  ApplicationEvent,
  ApplicationStatus,
  TrackedApplication,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";

import {
  buildDashboardApplicationStatusOverview,
  buildDashboardCalendarModel,
  countDashboardActiveApplications,
  countDashboardStrongMatches,
  countDashboardUpcomingInterviews,
  findDashboardEventApplication,
  selectRecommendedDashboardJobs,
  selectUpcomingDashboardEvents,
} from "./selectors";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    company: "Example",
    title: "Engineer",
    location: "Zurich",
    type: "Full-time",
    salary: "N/A",
    posted: "1h ago",
    experience: "Mid-level",
    department: "Engineering",
    match: 50,
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
  status: ApplicationStatus = "applied",
  overrides: Partial<TrackedApplication> = {},
): TrackedApplication {
  return {
    id: `application-${status}`,
    job: job({ id: `job-${status}` }),
    status,
    appliedAt: "2026-08-01T10:00:00.000Z",
    nextStep: "",
    notes: "",
    documents: [],
    ...overrides,
  };
}

function event(overrides: Partial<ApplicationEvent> = {}): ApplicationEvent {
  return {
    id: "event-1",
    applicationId: "application-applied",
    type: "interview",
    status: "scheduled",
    title: "Interview",
    startsAt: "2026-08-31T10:00:00.000Z",
    durationMinutes: 30,
    timezone: "Europe/Zurich",
    location: "Remote",
    notes: "",
    ...overrides,
  };
}

describe("dashboard selectors", () => {
  it("ranks recommendations by match and then posted time without mutation", () => {
    const nowMs = Date.parse("2026-08-31T12:00:00.000Z");
    const source = [
      job({ id: "older-high", match: 90, posted: "2h ago" }),
      job({ id: "lower", match: 80, posted: "1h ago" }),
      job({ id: "newer-high", match: 90, posted: "1h ago" }),
      job({ id: "last", match: 70, posted: "30m ago" }),
    ];

    expect(
      selectRecommendedDashboardJobs(source, nowMs).map((item) => item.id),
    ).toEqual(["newer-high", "older-high", "lower"]);
    expect(source.map((item) => item.id)).toEqual([
      "older-high",
      "lower",
      "newer-high",
      "last",
    ]);
  });

  it("counts only displayable strong matches and active applications", () => {
    const jobs = [
      job({ id: "strong", match: 80 }),
      job({ id: "weak", match: 79 }),
      job({ id: "manual-job-hidden", logo: "manual", match: 99 }),
    ];
    const applications = [
      application("draft"),
      application("applied"),
      application("interview"),
      application("assessment"),
      application("offer"),
      application("rejected"),
    ];

    expect(countDashboardStrongMatches(jobs)).toBe(1);
    expect(countDashboardActiveApplications(applications)).toBe(3);
  });

  it("sorts scheduled upcoming events and includes screenings in interviews", () => {
    const nowMs = Date.parse("2026-08-31T09:00:00.000Z");
    const upcoming = selectUpcomingDashboardEvents(
      [
        event({ id: "later", startsAt: "2026-08-31T12:00:00.000Z" }),
        event({ id: "past", startsAt: "2026-08-31T08:00:00.000Z" }),
        event({ id: "screen", type: "screening" }),
        event({ id: "assessment", type: "assessment", startsAt: "2026-08-31T11:00:00.000Z" }),
        event({ id: "done", status: "completed" }),
      ],
      nowMs,
    );

    expect(upcoming.map((item) => item.id)).toEqual([
      "screen",
      "assessment",
      "later",
    ]);
    expect(countDashboardUpcomingInterviews(upcoming)).toBe(2);
  });

  it("preserves status order, draft denominator, and accumulated arc offsets", () => {
    const overview = buildDashboardApplicationStatusOverview([
      application("draft"),
      application("applied"),
      application("interview"),
      application("offer"),
    ]);

    expect(overview.map((item) => item.status)).toEqual([
      "applied",
      "interview",
      "assessment",
      "offer",
      "rejected",
    ]);
    expect(overview.map((item) => item.percentage)).toEqual([25, 25, 0, 25, 0]);
    expect(overview.map((item) => item.arcOffset)).toEqual([0, 25, 50, 50, 75]);
  });

  it("uses the current time, next event, and fixed fallback as calendar anchors", () => {
    const scheduled = event({ startsAt: "2027-04-10T10:00:00.000Z" });
    const canceled = event({
      id: "canceled",
      status: "canceled",
      startsAt: "2027-04-11T10:00:00.000Z",
    });
    const currentTime = new Date(2026, 7, 31, 12);
    const current = buildDashboardCalendarModel({
      currentTime,
      upcomingEvents: [scheduled],
      events: [scheduled, canceled],
      monthOffset: 1,
    });
    const eventAnchored = buildDashboardCalendarModel({
      currentTime: null,
      upcomingEvents: [scheduled],
      events: [],
      monthOffset: 0,
    });
    const fallback = buildDashboardCalendarModel({
      currentTime: null,
      upcomingEvents: [],
      events: [],
      monthOffset: 0,
    });

    expect([current.month.getFullYear(), current.month.getMonth()]).toEqual([
      2026, 8,
    ]);
    expect(current.todayKey).toBe(getCalendarDateKey(currentTime));
    expect(current.days).toHaveLength(42);
    expect(current.eventDateKeys).toEqual(
      new Set([getCalendarDateKey(new Date(scheduled.startsAt))]),
    );
    expect([
      eventAnchored.month.getFullYear(),
      eventAnchored.month.getMonth(),
    ]).toEqual([2027, 3]);
    expect([fallback.month.getFullYear(), fallback.month.getMonth()]).toEqual([
      2026, 0,
    ]);
    expect(fallback.todayKey).toBe("");
  });

  it("finds the application for the next event", () => {
    const linked = application("applied");

    expect(findDashboardEventApplication([linked], event())?.id).toBe(
      linked.id,
    );
    expect(findDashboardEventApplication([linked], null)).toBeNull();
  });
});
