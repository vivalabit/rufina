import type {
  ApplicationDocument,
  ApplicationEventOutcome,
  ApplicationEventStatus,
  ApplicationEventType,
  ApplicationStatus,
} from "@/shared/types/application";

import {
  applicationEventOutcomes,
  applicationEventStatuses,
  applicationEventTypes,
  applicationStatuses,
  legacyMovedFromJobsNote,
} from "./model/constants";

export function getApplicationEventTypeLabel(type: ApplicationEventType) {
  return applicationEventTypes.find((item) => item.type === type)?.label ?? type;
}

export function getApplicationEventStatusLabel(
  status: ApplicationEventStatus,
) {
  return (
    applicationEventStatuses.find((item) => item.status === status)?.label ??
    status
  );
}

export function getApplicationEventOutcomeLabel(
  outcome?: ApplicationEventOutcome,
) {
  return outcome
    ? applicationEventOutcomes.find((item) => item.outcome === outcome)?.label ??
        outcome
    : "";
}

export function getApplicationTimelineEventLabel(type: ApplicationEventType) {
  const labels: Record<ApplicationEventType, string> = {
    screening: "Phone screen",
    interview: "Interview",
    assessment: "Assessment deadline",
    follow_up: "Follow-up",
    offer_deadline: "Offer deadline",
  };

  return labels[type];
}

export function formatApplicationEventDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date TBD";

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatApplicationEventTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time TBD";

  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatApplicationDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not set";

  const month = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ][date.getMonth()];
  return `${month} ${date.getDate()}, ${date.getFullYear()}`;
}

export function getApplicationStatusLabel(status: ApplicationStatus) {
  return applicationStatuses.find((item) => item.status === status)?.label ?? status;
}

export function getVisibleApplicationNotes(notes: string) {
  return notes.trim() === legacyMovedFromJobsNote ? "" : notes.trim();
}

export function getApplicationDocumentBadge(document: ApplicationDocument) {
  const extension = document.fileName.split(".").pop()?.trim().toUpperCase();
  if (extension && extension.length <= 5) return extension;
  if (document.fileType.includes("pdf")) return "PDF";
  if (document.fileType.includes("word")) return "DOC";
  if (document.fileType.includes("image")) return "IMG";
  return "FILE";
}
