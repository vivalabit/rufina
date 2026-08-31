import { getDisplayMatch } from "@/features/jobs/model/ai-match";
import type {
  ApplicationEvent,
  ApplicationStatus,
  ApplicationTimelineItem,
  TrackedApplication,
} from "@/shared/types/application";

import {
  formatApplicationDate,
  formatApplicationEventDate,
  formatApplicationEventTime,
  getApplicationTimelineEventLabel,
} from "../formatting";
import { trackedApplicationStatuses } from "./constants";
import type { ApplicationListFilter } from "./types";

export function getApplicationStatusCounts(applications: TrackedApplication[]) {
  return applications.reduce(
    (counts, application) => ({
      ...counts,
      [application.status]: counts[application.status] + 1,
    }),
    {
      draft: 0,
      applied: 0,
      interview: 0,
      assessment: 0,
      offer: 0,
      rejected: 0,
    } satisfies Record<ApplicationStatus, number>,
  );
}

export function filterAndSortApplications(
  applications: TrackedApplication[],
  filter: ApplicationListFilter,
) {
  const normalizedQuery = filter.query.trim().toLowerCase();

  return applications
    .filter((application) => {
      const matchesStatus =
        filter.status === "all" || application.status === filter.status;
      const matchesQuery =
        normalizedQuery.length === 0 ||
        [
          application.job.title,
          application.job.company,
          application.job.location,
          application.job.type,
          application.nextStep,
        ].some((value) => value.toLowerCase().includes(normalizedQuery));

      return matchesStatus && matchesQuery;
    })
    .sort((left, right) => {
      if (filter.sortBy === "AI Match") {
        return getDisplayMatch(right.job) - getDisplayMatch(left.job);
      }
      if (filter.sortBy === "Status") {
        const leftIndex = trackedApplicationStatuses.findIndex(
          (item) => item.status === left.status,
        );
        const rightIndex = trackedApplicationStatuses.findIndex(
          (item) => item.status === right.status,
        );
        return leftIndex - rightIndex;
      }

      const leftTime = Date.parse(left.appliedAt);
      const rightTime = Date.parse(right.appliedAt);
      return (
        (Number.isNaN(rightTime) ? 0 : rightTime) -
        (Number.isNaN(leftTime) ? 0 : leftTime)
      );
    });
}

export function getVisibleSelectedApplication(
  selectedApplication: TrackedApplication | null,
  visibleApplications: TrackedApplication[],
) {
  return selectedApplication &&
    visibleApplications.some(
      (application) => application.id === selectedApplication.id,
    )
    ? selectedApplication
    : visibleApplications[0] ?? null;
}

export function sortApplicationEvents(events: ApplicationEvent[]) {
  return [...events].sort(
    (left, right) =>
      new Date(left.startsAt).getTime() - new Date(right.startsAt).getTime(),
  );
}

export function getApplicationEventsFor(
  events: ApplicationEvent[],
  applicationId: string,
) {
  return sortApplicationEvents(
    events.filter((event) => event.applicationId === applicationId),
  );
}

export function getNextUpcomingApplicationEvent(
  events: ApplicationEvent[],
  nowMs: number,
) {
  return (
    events.find(
      (event) =>
        event.status === "scheduled" &&
        new Date(event.startsAt).getTime() >= nowMs,
    ) ?? null
  );
}

export function buildApplicationTimeline(
  application: TrackedApplication,
  events: ApplicationEvent[],
  nextEvent: ApplicationEvent | null,
): ApplicationTimelineItem[] {
  return [
    {
      label: application.status === "draft" ? "Application created" : "Applied",
      date: formatApplicationDate(application.appliedAt),
      state: application.status === "draft" ? "current" : "done",
    },
    ...events.map((event): ApplicationTimelineItem => {
      const isNextEvent = nextEvent?.id === event.id;
      const state: ApplicationTimelineItem["state"] =
        event.status === "canceled"
          ? "canceled"
          : event.outcome === "negative"
            ? "rejected"
            : event.status === "completed"
              ? "done"
              : isNextEvent
                ? "current"
                : "future";

      return {
        label: getApplicationTimelineEventLabel(event.type),
        date: `${formatApplicationEventDate(event.startsAt)} at ${formatApplicationEventTime(event.startsAt)}`,
        state,
        event,
      };
    }),
  ];
}
