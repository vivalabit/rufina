import { apiClient } from "@/shared/api/client";
import type { ApplicationDocument, TrackedApplication } from "@/shared/types/application";

import type {
  GeneratedApplicationDocumentPayload,
  StoredApplicationPayload,
  WorkspaceSourceFilePayload,
} from "./dto";
import {
  generatedDocumentToApplicationDocument,
  workspaceSourceToApplicationDocument,
} from "./mappers";
import { applicationPayloadForApi } from "./mappers";

export async function fetchApplications(signal?: AbortSignal) {
  return (await apiClient.json<StoredApplicationPayload[]>({
    path: "/applications",
    cache: "no-store",
    signal,
    errorMessage: "Applications could not be loaded",
  })).data;
}

export async function createApplication(
  application: TrackedApplication,
  signal?: AbortSignal,
) {
  return (await apiClient.json<StoredApplicationPayload>({
    path: "/applications",
    method: "POST",
    json: {
      id: application.id,
      data: applicationPayloadForApi(application),
    },
    signal,
    errorMessage: "Application could not be created",
  })).data;
}

export async function patchApplication(
  application: TrackedApplication,
  revision: number,
  signal?: AbortSignal,
) {
  return (await apiClient.json<StoredApplicationPayload>({
    path: `/applications/${encodeURIComponent(application.id)}`,
    method: "PATCH",
    ifMatch: revision,
    json: {
      data: applicationPayloadForApi(application),
      revision,
    },
    signal,
    errorMessage: "Application could not be saved",
  })).data;
}

export async function deleteApplication(
  applicationId: string,
  revision: number | null,
  signal?: AbortSignal,
) {
  await apiClient.empty({
    path: `/applications/${encodeURIComponent(applicationId)}`,
    method: "DELETE",
    ifMatch: revision,
    signal,
    errorMessage: "Application could not be deleted",
  });
}

export async function fetchApplicationAnalysis(
  applicationId: string,
  signal?: AbortSignal,
) {
  return (await apiClient.json<StoredApplicationPayload>({
    path: `/applications/${encodeURIComponent(applicationId)}/analysis`,
    cache: "no-store",
    signal,
    errorMessage: "Authoritative application analysis could not be loaded",
  })).data;
}

export async function fetchApplicationDocuments(
  applicationId: string,
  signal?: AbortSignal,
): Promise<ApplicationDocument[]> {
  const [sources, generated] = await Promise.all([
    apiClient.json<WorkspaceSourceFilePayload[]>({
      path: "/documents/workspace-sources/library",
      query: { applicationId },
      cache: "no-store",
      signal,
      errorMessage: "Application documents could not be loaded",
    }),
    apiClient.json<GeneratedApplicationDocumentPayload[]>({
      path: "/documents",
      query: { applicationId },
      cache: "no-store",
      signal,
      errorMessage: "Application documents could not be loaded",
    }),
  ]);
  return [
    ...sources.data
      .filter((source) => source.category === "Application Attachment")
      .map(workspaceSourceToApplicationDocument),
    ...generated.data.map((document) =>
      generatedDocumentToApplicationDocument(document),
    ),
  ];
}

export async function uploadApplicationAttachment(
  applicationId: string,
  file: Blob,
  metadata: { fileName: string; title: string },
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    applicationId,
    category: "Application Attachment",
    title: metadata.title,
    fileName: metadata.fileName,
  });
  const source = (await apiClient.json<WorkspaceSourceFilePayload>({
    path: "/documents/workspace-sources/upload",
    query,
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
    signal,
    errorMessage: "Application document could not be uploaded",
  })).data;
  return workspaceSourceToApplicationDocument(source);
}

export async function deleteApplicationAttachment(
  applicationId: string,
  document: ApplicationDocument,
  signal?: AbortSignal,
) {
  const path = document.artifactId
    ? `/documents/${encodeURIComponent(document.artifactId)}/attachments/${encodeURIComponent(applicationId)}`
    : document.sourceId
      ? `/documents/workspace-sources/${encodeURIComponent(document.sourceId)}?applicationId=${encodeURIComponent(applicationId)}`
      : null;
  if (!path) return;
  await apiClient.empty({
    path,
    method: "DELETE",
    signal,
    errorMessage: "Document could not be deleted",
  });
}

export async function downloadApplicationDocumentSource(
  downloadUrl: string,
  signal?: AbortSignal,
) {
  return (await apiClient.blob({
    path: downloadUrl,
    cache: "no-store",
    signal,
    errorMessage: "Selected resume could not be loaded",
  })).data;
}
