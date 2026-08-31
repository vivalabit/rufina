import type {
  ApplicationEvent,
  TrackedApplication,
} from "@/shared/types/application";

import type { CalendarEventFilter } from "./types";

function sortCalendarEvents(events: ApplicationEvent[]) {
  return [...events].sort(
    (left, right) =>
      new Date(left.startsAt).getTime() - new Date(right.startsAt).getTime(),
  );
}

export function selectCalendarDisplayEvents(
  events: ApplicationEvent[],
  demoEvents: ApplicationEvent[],
) {
  return events.length > 0 ? events : demoEvents;
}

export function filterCalendarEventsByType(
  events: ApplicationEvent[],
  activeType: CalendarEventFilter,
) {
  return activeType === "all"
    ? events
    : events.filter((event) => event.type === activeType);
}

export function selectCalendarMonthEvents(
  events: ApplicationEvent[],
  month: Date,
) {
  return events.filter((event) => {
    const date = new Date(event.startsAt);
    return (
      date.getFullYear() === month.getFullYear() &&
      date.getMonth() === month.getMonth()
    );
  });
}

export function selectUpcomingCalendarEvents(
  events: ApplicationEvent[],
  nowMs: number,
  limit = 3,
) {
  return sortCalendarEvents(
    events.filter(
      (event) =>
        event.status === "scheduled" &&
        new Date(event.startsAt).getTime() >= nowMs,
    ),
  ).slice(0, limit);
}

export function selectNextCalendarInterview(
  events: ApplicationEvent[],
  nowMs: number,
) {
  return (
    sortCalendarEvents(
      events.filter(
        (event) =>
          event.type === "interview" &&
          event.status === "scheduled" &&
          new Date(event.startsAt).getTime() >= nowMs,
      ),
    )[0] ?? null
  );
}

export function findCalendarEventApplication(
  applications: TrackedApplication[],
  event: ApplicationEvent,
) {
  return applications.find(
    (application) => application.id === event.applicationId,
  );
}

export function getCalendarEventCompany(
  applications: TrackedApplication[],
  event: ApplicationEvent,
) {
  const application = findCalendarEventApplication(applications, event);
  if (application) return application.job.company;
  if (event.type === "assessment") return "Assessment";
  if (event.type === "follow_up") return event.notes || "Reminder";
  if (event.type === "offer_deadline") return event.notes || "Offer";
  return event.title;
}
