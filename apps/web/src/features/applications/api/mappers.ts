import { resolveApiUrl } from "@/shared/api/config";
import { formatFileSize } from "@/shared/formatting/files";
import { normalizeStoredJobs } from "@/features/jobs/api/mappers";
import type {
  ApplicationDocument,
  ApplicationEvent,
  ApplicationEventOutcome,
  ApplicationEventStatus,
  ApplicationStatus,
  TrackedApplication,
} from "@/shared/types/application";

import type {
  ApplicationEventApiPayload,
  GeneratedApplicationDocumentPayload,
  WorkspaceSourceFilePayload,
} from "./dto";
import {
  applicationEventOutcomes,
  applicationEventStatuses,
  applicationEventTypes,
  applicationStatuses,
} from "../model/constants";

export function applicationPayloadForApi(application: TrackedApplication) {
  const payload: Partial<TrackedApplication> = { ...application };
  delete payload.documents;
  return payload;
}

export function normalizeApplicationDocuments(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((document): ApplicationDocument[] => {
    if (!document || typeof document !== "object") return [];
    const candidate = document as Partial<ApplicationDocument>;
    if (
      typeof candidate.id !== "string" ||
      typeof candidate.fileName !== "string" ||
      typeof candidate.downloadUrl !== "string"
    ) return [];

    return [{
      id: candidate.id,
      artifactId: candidate.artifactId?.trim() || undefined,
      sourceId: candidate.sourceId?.trim() || undefined,
      kind: candidate.kind ?? (candidate.artifactId ? "generated" : "uploaded"),
      title: candidate.title?.trim() || candidate.fileName,
      fileName: candidate.fileName,
      fileSize: candidate.fileSize?.trim() ?? "",
      fileType: candidate.fileType?.trim() ?? "application/octet-stream",
      uploadedAt: candidate.uploadedAt?.trim() ?? "",
      downloadUrl: candidate.downloadUrl,
      pendingFile: candidate.pendingFile,
    }];
  });
}

export function normalizeStoredApplications(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((application): TrackedApplication[] => {
    if (!application || typeof application !== "object") return [];
    const candidate = application as Partial<TrackedApplication>;
    const normalizedJobs = normalizeStoredJobs([candidate.job]);
    if (
      typeof candidate.id !== "string" ||
      normalizedJobs.length !== 1 ||
      !applicationStatuses.some((item) => item.status === candidate.status) ||
      typeof candidate.appliedAt !== "string" ||
      typeof candidate.nextStep !== "string" ||
      typeof candidate.notes !== "string"
    ) return [];

    return [{
      id: candidate.id,
      job: normalizedJobs[0],
      status: candidate.status as ApplicationStatus,
      appliedAt: candidate.appliedAt,
      nextStep: candidate.nextStep,
      notes: candidate.notes,
      documents: normalizeApplicationDocuments(candidate.documents),
    }];
  });
}

export function normalizeStoredApplicationEvents(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((event): ApplicationEvent[] => {
    if (!event || typeof event !== "object") return [];
    const candidate = event as Partial<ApplicationEvent>;
    const { id, applicationId, type, title, startsAt, durationMinutes, timezone, location, notes } = candidate;
    if (
      typeof id !== "string" ||
      typeof applicationId !== "string" ||
      !type ||
      !applicationEventTypes.some((item) => item.type === type) ||
      typeof title !== "string" ||
      typeof startsAt !== "string" ||
      typeof durationMinutes !== "number" ||
      typeof timezone !== "string" ||
      typeof location !== "string" ||
      typeof notes !== "string"
    ) return [];

    const storedStatus = candidate.status;
    const storedOutcome = candidate.outcome;
    const status: ApplicationEventStatus =
      applicationEventStatuses.some((item) => item.status === storedStatus) && storedStatus
        ? storedStatus
        : "scheduled";
    const outcome: ApplicationEventOutcome | undefined =
      applicationEventOutcomes.some((item) => item.outcome === storedOutcome)
        ? storedOutcome
        : undefined;
    return [{
      id,
      applicationId,
      type,
      status,
      outcome,
      title,
      startsAt,
      durationMinutes,
      timezone,
      location,
      notes,
    }];
  });
}

export function workspaceSourceToApplicationDocument(
  source: WorkspaceSourceFilePayload,
): ApplicationDocument {
  return {
    id: `source-${source.id}`,
    sourceId: source.id,
    kind: "uploaded",
    title: source.title,
    fileName: source.fileName,
    fileSize:
      source.fileSize || (source.sizeBytes ? formatFileSize(source.sizeBytes) : ""),
    fileType: source.fileType,
    uploadedAt: source.uploadedAt,
    downloadUrl: resolveApiUrl(source.downloadUrl),
  };
}

export function generatedDocumentToApplicationDocument(
  document: GeneratedApplicationDocumentPayload,
): ApplicationDocument {
  const current = document.versions.find(
    (version) => version.version === document.currentVersion,
  );

  return {
    id: `artifact-${document.id}`,
    artifactId: document.id,
    kind: "generated",
    title: document.title,
    fileName: current?.artifact?.fileName || `${document.title}.docx`,
    fileSize: "",
    fileType:
      current?.artifact?.contentType ||
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    uploadedAt: document.updatedAt,
    downloadUrl: resolveApiUrl(
      `/documents/${encodeURIComponent(document.id)}/download`,
    ),
  };
}

export function applicationEventToApiPayload(
  event: ApplicationEvent,
): ApplicationEventApiPayload {
  return {
    id: event.id,
    application_id: event.applicationId,
    data: event,
  };
}
