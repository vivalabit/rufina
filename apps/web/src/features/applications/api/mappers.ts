import { resolveApiUrl } from "@/shared/api/config";
import { formatFileSize } from "@/shared/formatting/files";
import {
  normalizeStoredJobLogo,
  normalizeStoredJobs,
} from "@/features/jobs/api/mappers";
import { normalizeDocumentPreparationSettings } from "@/features/applications/model/document-preparation";
import { getAiMatchAnalysisStatus } from "@/lib/ai-match";
import type {
  ApplicationDocument,
  ApplicationEvent,
  ApplicationEventOutcome,
  ApplicationEventStatus,
  ApplicationStatus,
  LegacyCandidateConfirmation,
  TrackedApplication,
} from "@/shared/types/application";
import type { Job } from "@/shared/types/job";

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
  // Migrated confirmations are read-only historical context. Keeping them out
  // of writes prevents an ordinary edit from turning them into current input.
  delete payload.legacyCandidateConfirmations;
  return payload;
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function stringList(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function normalizeApplicationJob(value: unknown, applicationId: string): Job | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<Job>;
  const normalized = normalizeStoredJobs([candidate])[0];
  const base = normalized ?? {
    id: stringValue(candidate.id, `legacy-job-${applicationId}`),
    title: stringValue(candidate.title, "Saved vacancy"),
    company: stringValue(candidate.company, "Unknown company"),
    location: stringValue(candidate.location),
    type: stringValue(candidate.type),
    salary: stringValue(candidate.salary),
    posted: stringValue(candidate.posted),
    experience: stringValue(candidate.experience),
    department: stringValue(candidate.department),
    match: typeof candidate.match === "number" ? candidate.match : 0,
    logo: "manual" as const,
    overview: stringValue(candidate.overview),
    responsibilities: stringList(candidate.responsibilities),
    requirements: stringList(candidate.requirements),
    skills: stringList(candidate.skills),
    salaryAverage: stringValue(candidate.salaryAverage),
    salaryMin: stringValue(candidate.salaryMin),
    salaryMax: stringValue(candidate.salaryMax),
    recommendations: Array.isArray(candidate.recommendations)
      ? candidate.recommendations
      : [],
    companyInfo: stringValue(candidate.companyInfo),
    reviews: stringList(candidate.reviews),
    similarJobs: stringList(candidate.similarJobs),
    applyUrl: stringValue(candidate.applyUrl) || undefined,
    sourceUrl: stringValue(candidate.sourceUrl) || undefined,
    addedAt: stringValue(candidate.addedAt) || undefined,
  } satisfies Job;
  const aiMatch = getAiMatchAnalysisStatus(candidate.aiMatch) === "current"
    ? candidate.aiMatch
    : undefined;
  const job = { ...base, aiMatch };
  return { ...job, logo: normalizeStoredJobLogo(job) };
}

function normalizeLegacyConfirmations(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): LegacyCandidateConfirmation[] => {
    if (!item || typeof item !== "object") return [];
    const candidate = item as Partial<LegacyCandidateConfirmation>;
    if (
      typeof candidate.questionId !== "string"
      || !["yes", "no", "partial"].includes(candidate.response ?? "")
    ) return [];
    return [{
      questionId: candidate.questionId,
      requirement: stringValue(candidate.requirement),
      response: candidate.response as LegacyCandidateConfirmation["response"],
      exampleText: stringValue(candidate.exampleText),
      blocking: candidate.blocking === true,
      updatedAt: stringValue(candidate.updatedAt),
    }];
  });
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
    const candidate = application as Partial<TrackedApplication> & {
      applied_at?: unknown;
      next_step?: unknown;
    };
    const id = stringValue(candidate.id).trim();
    const job = normalizeApplicationJob(candidate.job, id);
    if (!id || !job) return [];

    const status = applicationStatuses.some((item) => item.status === candidate.status)
      ? candidate.status as ApplicationStatus
      : "draft";
    const appliedAt = stringValue(candidate.appliedAt)
      || stringValue(candidate.applied_at);
    const nextStep = stringValue(candidate.nextStep)
      || stringValue(candidate.next_step);
    const legacyCandidateConfirmations = normalizeLegacyConfirmations(
      candidate.legacyCandidateConfirmations,
    );

    return [{
      id,
      job,
      status,
      appliedAt,
      nextStep,
      notes: stringValue(candidate.notes),
      documents: normalizeApplicationDocuments(candidate.documents),
      documentPreparation: normalizeDocumentPreparationSettings(
        candidate.documentPreparation,
      ),
      ...(legacyCandidateConfirmations.length
        ? { legacyCandidateConfirmations }
        : {}),
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
