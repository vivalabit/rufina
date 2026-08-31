import { getApplicationEventTypeLabel } from "@/features/applications/formatting";
import { createClientId } from "@/lib/client-id";
import type {
  ApplicationEvent,
  ApplicationEventDraft,
  TrackedApplication,
} from "@/shared/types/application";

export function getLocalTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function toDateTimeLocalValue(date: Date) {
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

export function createDefaultEventDraft(
  application: TrackedApplication,
): ApplicationEventDraft {
  const start = new Date();
  start.setDate(start.getDate() + 5);
  start.setHours(10, 0, 0, 0);

  return {
    type: "screening",
    status: "scheduled",
    outcome: "",
    title: `${application.job.company} screening`,
    startsAt: toDateTimeLocalValue(start),
    durationMinutes: "30",
    timezone: getLocalTimezone(),
    location: "",
    notes: "",
  };
}

export function createEventDraftFromEvent(
  event: ApplicationEvent,
): ApplicationEventDraft {
  return {
    id: event.id,
    type: event.type,
    status: event.status,
    outcome: event.outcome ?? "",
    title: event.title,
    startsAt: toDateTimeLocalValue(new Date(event.startsAt)),
    durationMinutes: event.durationMinutes.toString(),
    timezone: event.timezone,
    location: event.location,
    notes: event.notes,
  };
}

export function createApplicationEvent(
  applicationId: string,
  draft: ApplicationEventDraft,
): ApplicationEvent {
  const startDate = new Date(draft.startsAt);
  const startsAt = Number.isNaN(startDate.getTime())
    ? new Date().toISOString()
    : startDate.toISOString();

  return {
    id: draft.id ?? createClientId("application-event"),
    applicationId,
    type: draft.type,
    status: draft.status,
    outcome:
      draft.status === "completed" ? draft.outcome || undefined : undefined,
    title: draft.title.trim() || getApplicationEventTypeLabel(draft.type),
    startsAt,
    durationMinutes: Number.parseInt(draft.durationMinutes, 10) || 30,
    timezone: draft.timezone.trim() || getLocalTimezone(),
    location: draft.location.trim(),
    notes: draft.notes.trim(),
  };
}
