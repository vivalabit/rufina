import type { Job } from "@/shared/types/job";

export type PreparationDocumentType = "tailored_resume" | "cover_letter";
export type PreparationLanguage = "Auto" | "English" | "German";
export type PreparationPageSize = "A4" | "Letter";
export type PreparationResumeMaxPages = 1 | 2 | 3;

export type GenerationDocumentState =
  | "queued"
  | "running"
  | "completed"
  | "failed";
export type GenerationExecutionState = GenerationDocumentState;

export type GenerationError = {
  code: string;
  message: string;
  retryable: boolean;
};

export type GeneratedFile = {
  fileName: string;
  contentType: string;
  downloadUrl: string;
};

export type GenerationDocumentResult = {
  documentType: PreparationDocumentType;
  state: GenerationDocumentState;
  files: GeneratedFile[];
  error: GenerationError | null;
};

export type GenerationResult = {
  executionId: string;
  state: GenerationExecutionState;
  documents: GenerationDocumentResult[];
  error: GenerationError | null;
};

export type PersistedGenerationResult = {
  executionId: string;
  state: GenerationExecutionState;
  documentResults: GenerationDocumentResult[];
  error: GenerationError | null;
};

export type SubmissionDocumentSelection = {
  documentId: string;
  version: number | null;
};

export type DocumentPreparationSettings = {
  documentTypes: PreparationDocumentType[];
  language: PreparationLanguage;
  formatting: {
    pageSize: PreparationPageSize;
    resumeTemplateId: string;
    resumeMaxPages: PreparationResumeMaxPages;
    coverLetterTemplateId: string;
  };
  submission: Record<
    PreparationDocumentType,
    SubmissionDocumentSelection | null
  >;
  latestGeneration: PersistedGenerationResult | null;
  userPreferences: string;
};

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

export type LegacyCandidateConfirmation = {
  questionId: string;
  requirement: string;
  response: "yes" | "no" | "partial";
  exampleText: string;
  blocking: boolean;
  updatedAt: string;
};

export type TrackedApplication = {
  id: string;
  job: Job;
  status: ApplicationStatus;
  appliedAt: string;
  nextStep: string;
  notes: string;
  documents: ApplicationDocument[];
  documentPreparation?: DocumentPreparationSettings;
  legacyCandidateConfirmations?: LegacyCandidateConfirmation[];
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
