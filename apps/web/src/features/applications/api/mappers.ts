import { resolveApiUrl } from "@/shared/api/config";
import { formatFileSize } from "@/shared/formatting/files";
import type {
  ApplicationDocument,
  ApplicationEvent,
} from "@/shared/types/application";

import type {
  ApplicationEventApiPayload,
  GeneratedApplicationDocumentPayload,
  WorkspaceSourceFilePayload,
} from "./dto";

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
  apiBaseUrl: string,
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
    downloadUrl: `${apiBaseUrl}/documents/${encodeURIComponent(document.id)}/download`,
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
