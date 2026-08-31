import { trackedApplicationStatuses } from "@/features/applications/model/constants";
import { sortApplicationEvents } from "@/features/applications/model/selectors";
import { formatCalendarMonthLabel } from "@/features/calendar/formatting";
import {
  getCalendarDateKey,
  getDashboardCalendarDays,
} from "@/features/calendar/model/date-grid";
import {
  getDisplayMatch,
  hasDisplayableMatch,
} from "@/features/jobs/model/ai-match";
import { getJobPostedTime } from "@/features/jobs/model/selectors";
import type {
  ApplicationEvent,
  TrackedApplication,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";

import {
  dashboardActiveApplicationStatuses,
  dashboardApplicationStatusColors,
} from "./constants";

export function selectRecommendedDashboardJobs(
  jobs: Job[],
  nowMs: number,
  limit = 3,
) {
  return [...jobs]
    .sort(
      (left, right) =>
        getDisplayMatch(right) - getDisplayMatch(left) ||
        getJobPostedTime(right, nowMs) - getJobPostedTime(left, nowMs),
    )
    .slice(0, limit);
}

export function countDashboardStrongMatches(jobs: Job[]) {
  return jobs.filter(
    (job) => hasDisplayableMatch(job) && getDisplayMatch(job) >= 80,
  ).length;
}

export function countDashboardActiveApplications(
  applications: TrackedApplication[],
) {
  return applications.filter((application) =>
    dashboardActiveApplicationStatuses.includes(application.status),
  ).length;
}

export function selectUpcomingDashboardEvents(
  events: ApplicationEvent[],
  nowMs: number,
) {
  return sortApplicationEvents(
    events.filter(
      (event) =>
        event.status === "scheduled" &&
        new Date(event.startsAt).getTime() >= nowMs,
    ),
  );
}

export function countDashboardUpcomingInterviews(
  upcomingEvents: ApplicationEvent[],
) {
  return upcomingEvents.filter(
    (event) => event.type === "interview" || event.type === "screening",
  ).length;
}

export function findDashboardEventApplication(
  applications: TrackedApplication[],
  event: ApplicationEvent | null,
) {
  return event
    ? applications.find(
        (application) => application.id === event.applicationId,
      ) ?? null
    : null;
}

export function buildDashboardApplicationStatusOverview(
  applications: TrackedApplication[],
) {
  let statusArcOffset = 0;

  return trackedApplicationStatuses.map((item) => {
    const count = applications.filter(
      (application) => application.status === item.status,
    ).length;
    const arcPercentage =
      applications.length > 0 ? (count / applications.length) * 100 : 0;
    const arcOffset = statusArcOffset;
    statusArcOffset += arcPercentage;

    return {
      ...item,
      count,
      percentage: Math.round(arcPercentage),
      arcPercentage,
      arcOffset,
      color: dashboardApplicationStatusColors[item.status],
    };
  });
}

type DashboardCalendarInput = {
  currentTime: Date | null;
  upcomingEvents: ApplicationEvent[];
  events: ApplicationEvent[];
  monthOffset: number;
};

export function buildDashboardCalendarModel({
  currentTime,
  upcomingEvents,
  events,
  monthOffset,
}: DashboardCalendarInput) {
  const calendarAnchor =
    currentTime ??
    (upcomingEvents[0]
      ? new Date(upcomingEvents[0].startsAt)
      : new Date(2026, 0, 1));
  const month = new Date(
    calendarAnchor.getFullYear(),
    calendarAnchor.getMonth() + monthOffset,
    1,
  );

  return {
    month,
    days: getDashboardCalendarDays(month),
    monthLabel: formatCalendarMonthLabel(month),
    todayKey: currentTime ? getCalendarDateKey(currentTime) : "",
    eventDateKeys: new Set(
      events
        .filter((event) => event.status === "scheduled")
        .map((event) => getCalendarDateKey(new Date(event.startsAt))),
    ),
  };
}
