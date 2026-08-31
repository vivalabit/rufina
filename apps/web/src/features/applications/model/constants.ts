import type {
  ApplicationEventOutcome,
  ApplicationEventStatus,
  ApplicationEventType,
  ApplicationStatus,
} from "@/shared/types/application";

import type { ApplicationSortBy, ManualApplicationDraft } from "./types";

export const applicationStatuses: Array<{
  status: ApplicationStatus;
  label: string;
}> = [
  { status: "draft", label: "Preparing" },
  { status: "applied", label: "Applied" },
  { status: "interview", label: "Interview" },
  { status: "assessment", label: "Assessment" },
  { status: "offer", label: "Offer" },
  { status: "rejected", label: "Rejected" },
];

export const trackedApplicationStatuses = applicationStatuses.filter(
  (item) => item.status !== "draft",
);

export const applicationSortOptions: ApplicationSortBy[] = [
  "Date applied",
  "AI Match",
  "Status",
];

export const applicationStatusStyles: Record<ApplicationStatus, string> = {
  draft: "border-[#fa5d00]/40 bg-[#fa5d00]/14 text-accent",
  applied: "border-accent/35 bg-accent/12 text-accent",
  interview: "border-success/35 bg-success/12 text-success",
  assessment: "border-[#fa5d00]/40 bg-[#fa5d00]/14 text-accent",
  offer: "border-success/45 bg-success/18 text-success",
  rejected: "border-[#fa5d00]/45 bg-[#fa5d00]/13 text-[#fa5d00]",
};

export const applicationEventTypes: Array<{
  type: ApplicationEventType;
  label: string;
}> = [
  { type: "screening", label: "Screening" },
  { type: "interview", label: "Interview" },
  { type: "assessment", label: "Assessment deadline" },
  { type: "follow_up", label: "Follow-up" },
  { type: "offer_deadline", label: "Offer deadline" },
];

export const applicationEventStatuses: Array<{
  status: ApplicationEventStatus;
  label: string;
}> = [
  { status: "scheduled", label: "Scheduled" },
  { status: "completed", label: "Completed" },
  { status: "canceled", label: "Canceled" },
];

export const applicationEventOutcomes: Array<{
  outcome: ApplicationEventOutcome;
  label: string;
}> = [
  { outcome: "positive", label: "Positive" },
  { outcome: "neutral", label: "Neutral" },
  { outcome: "negative", label: "Rejected" },
];

export const defaultManualApplicationDraft: ManualApplicationDraft = {
  title: "",
  company: "",
  location: "",
  applyUrl: "",
  overview: "",
  status: "applied",
  documents: [],
};

export const legacyMovedFromJobsNote = "Moved from Jobs after applying.";
