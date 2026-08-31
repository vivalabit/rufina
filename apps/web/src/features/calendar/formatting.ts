import type {
  ApplicationEvent,
  TrackedApplication,
} from "@/shared/types/application";

export function formatCalendarMonthLabel(month: Date) {
  return month.toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
}

export function formatCalendarLongDate(date: Date) {
  return date.toLocaleDateString("en-US", { dateStyle: "long" });
}

export function formatInterviewPreparationPrompt(
  event: ApplicationEvent,
  application: TrackedApplication | undefined,
  basePrompt: string,
) {
  const startsAt = new Date(event.startsAt).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });

  return [
    basePrompt,
    `Interview: ${event.title}`,
    application
      ? `Role: ${application.job.title} at ${application.job.company}`
      : "",
    `When: ${startsAt} (${event.timezone})`,
    event.location ? `Location: ${event.location}` : "",
    event.notes ? `Notes: ${event.notes}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}
