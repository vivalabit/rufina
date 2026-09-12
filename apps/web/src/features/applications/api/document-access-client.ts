import { apiClient } from "@/shared/api/client";

function normalizeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

async function fetchDocumentList<T>(
  query: { applicationId?: string; jobId?: string },
  errorMessage: string,
  signal?: AbortSignal,
) {
  return (await apiClient.json<T[]>({
    path: "/documents",
    query,
    signal,
    errorMessage,
  }, normalizeArray<T>)).data;
}

export function fetchApplicationDocuments<T>(
  applicationId: string,
  signal?: AbortSignal,
) {
  return fetchDocumentList<T>(
    { applicationId },
    "Application documents are temporarily unavailable",
    signal,
  );
}

export function fetchJobDocuments<T>(
  jobId: string,
  signal?: AbortSignal,
) {
  return fetchDocumentList<T>(
    { jobId },
    "Saved vacancy documents are temporarily unavailable",
    signal,
  );
}

export async function attachDocument<T>(
  documentId: string,
  applicationId: string,
  signal?: AbortSignal,
) {
  return (await apiClient.json<T>({
    path: `/documents/${encodeURIComponent(documentId)}/attachments`,
    method: "POST",
    json: { applicationId },
    signal,
    errorMessage: "The document could not be attached to the application",
  })).data;
}

export async function fetchDocument<T>(
  documentId: string,
  signal?: AbortSignal,
) {
  return (await apiClient.json<T>({
    path: `/documents/${encodeURIComponent(documentId)}`,
    cache: "no-store",
    signal,
    errorMessage: "The saved document details are temporarily unavailable.",
  })).data;
}

export async function downloadDocument(
  documentId: string,
  version?: number,
  signal?: AbortSignal,
) {
  return (await apiClient.blob({
    path: `/documents/${encodeURIComponent(documentId)}/download`,
    query: version === undefined ? undefined : { version },
    cache: "no-store",
    signal,
    errorMessage: "The saved document is temporarily unavailable.",
  })).data;
}

export async function downloadDocumentPdf(
  documentId: string,
  version?: number,
  signal?: AbortSignal,
) {
  return (await apiClient.blob({
    path: `/documents/${encodeURIComponent(documentId)}/pdf`,
    query: version === undefined ? undefined : { version },
    cache: "no-store",
    signal,
    errorMessage: "The PDF preview is temporarily unavailable.",
  })).data;
}

export async function fetchDocumentVersions<T>(
  documentId: string,
  offset: number,
  signal?: AbortSignal,
) {
  return (await apiClient.json<{ items: T[]; total: number }>({
    path: `/documents/${encodeURIComponent(documentId)}/versions`,
    query: { offset, limit: 20 },
    signal,
    errorMessage: "Version history could not be loaded",
  })).data;
}

export function documentDownloadUrl(documentId: string, version?: number) {
  return apiClient.url(
    `/documents/${encodeURIComponent(documentId)}/download`,
    version === undefined ? undefined : { version },
  ).toString();
}

export function documentPdfUrl(documentId: string, version?: number) {
  return apiClient.url(
    `/documents/${encodeURIComponent(documentId)}/pdf`,
    version === undefined ? undefined : { version },
  ).toString();
}
