import { requestJson } from "@/lib/api-client";
import { apiBaseUrl } from "@/shared/api/config";
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
import { applicationPayloadForStorage } from "../browser-storage/serialization";

export async function fetchApplications(signal?: AbortSignal) {
  return (await requestJson<StoredApplicationPayload[]>(
    `${apiBaseUrl}/applications`,
    { cache: "no-store", signal },
    { errorMessage: "Applications could not be loaded" },
  )).data;
}

export async function importLegacyApplications(
  applications: TrackedApplication[],
  signal?: AbortSignal,
) {
  return (await requestJson<StoredApplicationPayload[]>(
    `${apiBaseUrl}/applications`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        applications: applications.map((application) => ({
          id: application.id,
          data: applicationPayloadForStorage(application),
        })),
      }),
      signal,
    },
    { errorMessage: "Legacy applications could not be imported" },
  )).data;
}

export async function createApplication(
  application: TrackedApplication,
  signal?: AbortSignal,
) {
  return (await requestJson<StoredApplicationPayload>(
    `${apiBaseUrl}/applications`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: application.id,
        data: applicationPayloadForStorage(application),
      }),
      signal,
    },
    { errorMessage: "Application could not be created" },
  )).data;
}

export async function patchApplication(
  application: TrackedApplication,
  revision: number,
  signal?: AbortSignal,
) {
  return (await requestJson<StoredApplicationPayload>(
    `${apiBaseUrl}/applications/${encodeURIComponent(application.id)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "If-Match": `"${revision}"`,
      },
      body: JSON.stringify({
        data: applicationPayloadForStorage(application),
        revision,
      }),
      signal,
    },
    { errorMessage: "Application could not be saved" },
  )).data;
}

export async function deleteApplication(
  applicationId: string,
  revision: number | null,
  signal?: AbortSignal,
) {
  await requestJson<null>(
    `${apiBaseUrl}/applications/${encodeURIComponent(applicationId)}`,
    {
      method: "DELETE",
      headers: revision === null ? undefined : { "If-Match": `"${revision}"` },
      signal,
    },
    { errorMessage: "Application could not be deleted" },
  );
}

export async function fetchApplicationDocuments(
  applicationId: string,
  signal?: AbortSignal,
): Promise<ApplicationDocument[]> {
  const encodedId = encodeURIComponent(applicationId);
  const [sources, generated] = await Promise.all([
    requestJson<WorkspaceSourceFilePayload[]>(
      `${apiBaseUrl}/documents/workspace-sources/library?applicationId=${encodedId}`,
      { cache: "no-store", signal },
      { errorMessage: "Application documents could not be loaded" },
    ),
    requestJson<GeneratedApplicationDocumentPayload[]>(
      `${apiBaseUrl}/documents?applicationId=${encodedId}`,
      { cache: "no-store", signal },
      { errorMessage: "Application documents could not be loaded" },
    ),
  ]);
  return [
    ...sources.data
      .filter((source) => source.category === "Application Attachment")
      .map(workspaceSourceToApplicationDocument),
    ...generated.data.map((document) =>
      generatedDocumentToApplicationDocument(document, apiBaseUrl),
    ),
  ];
}

export async function uploadApplicationAttachment(
  applicationId: string,
  file: Blob,
  metadata: { fileName: string; title: string; legacyDocumentId?: string },
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    applicationId,
    category: "Application Attachment",
    title: metadata.title,
    fileName: metadata.fileName,
  });
  if (metadata.legacyDocumentId) query.set("legacyDocumentId", metadata.legacyDocumentId);
  const source = (await requestJson<WorkspaceSourceFilePayload>(
    `${apiBaseUrl}/documents/workspace-sources/upload?${query}`,
    {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
      signal,
    },
    { errorMessage: "Application document could not be uploaded" },
  )).data;
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
  await requestJson<null>(
    `${apiBaseUrl}${path}`,
    { method: "DELETE", signal },
    { errorMessage: "Document could not be deleted" },
  );
}
