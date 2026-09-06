import type { Job } from "@/shared/types/job";

export type ApplicationStatus = "draft" | "applied" | "interview" | "assessment" | "offer" | "rejected";
export type ApplicationEventType = "screening" | "interview" | "assessment" | "follow_up" | "offer_deadline";
export type ApplicationEventStatus = "scheduled" | "completed" | "canceled";
export type ApplicationEventOutcome = "positive" | "negative" | "neutral";

export type ApplicationDocument = {
  id: string;
  artifactId?: string;
  sourceId?: string;
  kind: "generated" | "uploaded" | "profile";
  title: string;
  fileName: string;
  fileSize: string;
  fileType: string;
  uploadedAt: string;
  downloadUrl: string;
  pendingFile?: File;
};

export type TrackedApplication = {
  id: string;
  job: Job;
  status: ApplicationStatus;
  appliedAt: string;
  nextStep: string;
  notes: string;
  documents: ApplicationDocument[];
};

export type ApplicationEvent = {
  id: string;
  applicationId: string;
  type: ApplicationEventType;
  status: ApplicationEventStatus;
  outcome?: ApplicationEventOutcome;
  title: string;
  startsAt: string;
  durationMinutes: number;
  timezone: string;
  location: string;
  notes: string;
};

export type ApplicationEventDraft = {
  type: ApplicationEventType;
  id?: string;
  status: ApplicationEventStatus;
  outcome: ApplicationEventOutcome | "";
  title: string;
  startsAt: string;
  durationMinutes: string;
  timezone: string;
  location: string;
  notes: string;
};

export type ApplicationTimelineItem = {
  label: string;
  date: string;
  state: "done" | "current" | "future" | "canceled" | "rejected";
  event?: ApplicationEvent;
};
