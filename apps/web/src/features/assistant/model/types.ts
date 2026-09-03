import type { AiSource } from "@/lib/ai-source";

export type AssistantLaunch = {
  id: string;
  prompt: string;
  contextKind: "profile" | "job" | "application";
  contextId?: string;
  autoSubmit?: boolean;
};

export type AssistantContextKind = AssistantLaunch["contextKind"];

export type AssistantActionFieldPreview = {
  label: string;
  before: string;
  after: string;
};

export type AssistantActionPreview = {
  id: string;
  type: "add_application_note" | "update_application_next_step" | "create_interview_event" | "save_document" | "update_profile_field";
  title: string;
  description: string;
  contextKind: AssistantContextKind;
  contextId: string;
  fields: AssistantActionFieldPreview[];
  payload: Record<string, unknown>;
  status: "preview" | "applying" | "applied" | "error";
  resultMessage: string;
};

export type AssistantMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  source?: AiSource;
  status?: "generating" | "complete" | "stopped" | "error";
  actions?: AssistantActionPreview[];
};

export type AssistantThread = {
  id: string;
  title: string;
  contextKind: AssistantContextKind;
  contextId: string;
  providerSessionId?: string | null;
  archived: boolean;
  createdAt: string;
  updatedAt: string;
  messages: AssistantMessage[];
};

export type AssistantDocumentVersion = {
  id: string;
  version: number;
  content: string;
  createdAt: string;
  artifact?: {
    fileName: string;
    contentType: string;
  } | null;
};

export type AssistantDocument = {
  id: string;
  type: "cover_letter" | "tailored_resume";
  title: string;
  jobId: string | null;
  applicationIds: string[];
  currentVersion: number;
  createdAt: string;
  updatedAt: string;
  versions: AssistantDocumentVersion[];
};

export type AssistantDocumentDraft = {
  id: string;
  type: "cover_letter";
  title: string;
  content: string;
  jobId: string;
  applicationId: string;
};

export type AssistantAppliedAction = {
  actionId: string;
  type: AssistantActionPreview["type"];
  status: "applied";
  message: string;
  resourceKind: "application" | "event" | "document" | "profile";
  resource: Record<string, unknown>;
};

export type AssistantDocumentAttachment = {
  artifactId: string;
  title: string;
  fileName: string;
  fileType: string;
  uploadedAt: string;
  downloadUrl: string;
};

export type AssistantSseEvent = {
  event: string;
  data: Record<string, unknown>;
};
