import { normalizeStoredJobs } from "@/features/jobs/browser-storage/normalizers";
import { isInlineDataUrl } from "@/shared/browser-storage/data-url";
import type {
  ApplicationDocument,
  ApplicationEvent,
  ApplicationEventOutcome,
  ApplicationEventStatus,
  ApplicationStatus,
  TrackedApplication,
} from "@/shared/types/application";

import {
  applicationEventOutcomes,
  applicationEventStatuses,
  applicationEventTypes,
  applicationStatuses,
} from "../model/constants";

export const legacyDemoApplicationIds = new Set([
  "application-stripe-senior-product-designer",
  "application-figma-product-design-lead",
  "application-manual-job-demo-novara",
  "application-manual-job-demo-cirruspay",
  "application-manual-job-demo-alpine-grid",
  "application-manual-job-demo-luma-health",
]);

function legacyFileName(index: number, dataUrl: string) {
  const contentType =
    /^data:([^;,]+)/i.exec(dataUrl.trim())?.[1]?.toLowerCase() ?? "";
  const extensionByType: Record<string, string> = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
      "docx",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
  };
  const extension = extensionByType[contentType];
  return `legacy-document-${index + 1}${extension ? `.${extension}` : ""}`;
}

export function normalizeApplicationDocuments(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((document, index): ApplicationDocument[] => {
    if (!document || typeof document !== "object") return [];
    const candidate = document as Partial<ApplicationDocument> & {
      dataUrl?: string;
      data_url?: string;
      file_name?: string;
    };
    const rawLegacyDataUrl =
      candidate.legacyDataUrl ?? candidate.dataUrl ?? candidate.data_url ?? "";
    const legacyDataUrl = isInlineDataUrl(rawLegacyDataUrl)
      ? rawLegacyDataUrl.trim()
      : "";
    const fileName =
      candidate.fileName?.trim() ||
      candidate.file_name?.trim() ||
      (legacyDataUrl ? legacyFileName(index, legacyDataUrl) : "");
    const downloadUrl =
      candidate.downloadUrl ??
      (rawLegacyDataUrl && !isInlineDataUrl(rawLegacyDataUrl)
        ? rawLegacyDataUrl
        : "");

    if (!fileName || (!downloadUrl && !legacyDataUrl && !candidate.pendingFile)) {
      return [];
    }

    return [
      {
        id:
          typeof candidate.id === "string" && candidate.id.trim()
            ? candidate.id
            : `legacy-application-document-${index + 1}`,
        artifactId: candidate.artifactId?.trim() || undefined,
        sourceId: candidate.sourceId?.trim() || undefined,
        kind: candidate.kind ??
          (candidate.artifactId ? "generated" : "uploaded"),
        title:
          candidate.title?.trim() ||
          fileName.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() ||
          fileName,
        fileName,
        fileSize: candidate.fileSize?.trim() ?? "",
        fileType:
          candidate.fileType?.trim() ?? "application/octet-stream",
        uploadedAt: candidate.uploadedAt?.trim() ?? "",
        downloadUrl,
        legacyDataUrl: legacyDataUrl || undefined,
        pendingFile: candidate.pendingFile,
      },
    ];
  });
}

export function normalizeStoredApplications(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((application): TrackedApplication[] => {
    if (!application || typeof application !== "object") return [];
    const candidate = application as Partial<TrackedApplication>;
    const normalizedJobs = normalizeStoredJobs([candidate.job]);
    const isValidApplication =
      typeof candidate.id === "string" &&
      candidate.job !== undefined &&
      normalizedJobs.length === 1 &&
      applicationStatuses.some((item) => item.status === candidate.status) &&
      typeof candidate.appliedAt === "string" &&
      typeof candidate.nextStep === "string" &&
      typeof candidate.notes === "string";

    if (!isValidApplication) return [];

    return [
      {
        id: candidate.id as string,
        job: normalizedJobs[0],
        status: candidate.status as ApplicationStatus,
        appliedAt: candidate.appliedAt as string,
        nextStep: candidate.nextStep as string,
        notes: candidate.notes as string,
        documents: normalizeApplicationDocuments(candidate.documents),
      },
    ];
  });
}

export function removeLegacyDemoApplications(
  applications: TrackedApplication[],
) {
  return applications.filter(
    (application) => !legacyDemoApplicationIds.has(application.id),
  );
}

export function removeLegacyDemoApplicationEvents(events: ApplicationEvent[]) {
  return events.filter(
    (event) => !legacyDemoApplicationIds.has(event.applicationId),
  );
}

export function normalizeStoredApplicationEvents(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((event): ApplicationEvent[] => {
    if (!event || typeof event !== "object") return [];
    const candidate = event as Partial<ApplicationEvent>;
    const {
      id,
      applicationId,
      type,
      title,
      startsAt,
      durationMinutes,
      timezone,
      location,
      notes,
    } = candidate;

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
    ) {
      return [];
    }

    const storedStatus = candidate.status;
    const storedOutcome = candidate.outcome;
    const status: ApplicationEventStatus =
      applicationEventStatuses.some((item) => item.status === storedStatus) &&
      storedStatus
        ? storedStatus
        : "scheduled";
    const outcome: ApplicationEventOutcome | undefined =
      applicationEventOutcomes.some((item) => item.outcome === storedOutcome)
        ? storedOutcome
        : undefined;

    return [
      {
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
      },
    ];
  });
}
