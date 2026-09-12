"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BriefcaseBusiness,
  CircleDot,
  Download,
  Eye,
  ExternalLink,
  FileText,
  LoaderCircle,
  MapPin,
  Paperclip,
  RefreshCw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { DocumentPdfPreview } from "@/components/document-pdf-preview";
import {
  attachDocument,
  documentDownloadUrl,
  fetchApplicationDocuments,
  fetchDocumentVersions,
  fetchJobDocuments,
} from "@/features/applications/api/document-access-client";
import {
  formatApplicationDate,
  getApplicationStatusLabel,
} from "@/features/applications/formatting";
import { applicationStatusStyles } from "@/features/applications/model/constants";
import { normalizeJobsChJobUrl } from "@/lib/job-url";
import { cn } from "@/lib/utils";
import type { ApplicationStatus } from "@/shared/types/application";
import type { Job } from "@/shared/types/job";

type WorkspaceApplicationDocument = {
  id: string;
  artifactId?: string;
  title: string;
  fileName: string;
  fileSize: string;
  fileType: string;
  uploadedAt: string;
  downloadUrl: string;
};

type StoredDocumentVersion = {
  id: string;
  version: number;
  createdAt: string;
  hasRenderedArtifact?: boolean;
  artifact?: {
    fileName?: string;
    contentType?: string;
  } | null;
};

type StoredDocument = {
  id: string;
  type: "cover_letter" | "tailored_resume";
  title: string;
  jobId: string | null;
  applicationIds: string[];
  currentVersion: number;
  createdAt: string;
  updatedAt: string;
  versions: StoredDocumentVersion[];
  versionsTotal: number;
  versionsHasMore: boolean;
};

type WorkspaceApplication = {
  id: string;
  status: ApplicationStatus;
  nextStep: string;
  notes: string;
  job: Pick<
    Job,
    | "id"
    | "title"
    | "company"
    | "location"
    | "type"
    | "overview"
    | "responsibilities"
    | "requirements"
    | "skills"
    | "applyUrl"
    | "sourceUrl"
  >;
  documents: WorkspaceApplicationDocument[];
};

type ApplicationWorkspaceProps = {
  application: WorkspaceApplication | null;
  backLabel?: string;
  onBack: () => void;
  onDocumentAttached: (
    applicationId: string,
    document: {
      artifactId: string;
      title: string;
      fileName: string;
      fileType: string;
      uploadedAt: string;
      downloadUrl: string;
    },
  ) => void;
};

function getFileBadge(fileName: string, fileType: string) {
  const extension = fileName.split(".").pop()?.trim().toUpperCase();
  if (extension && extension.length <= 5) return extension;
  if (fileType.includes("pdf")) return "PDF";
  if (fileType.includes("word")) return "DOC";
  return "FILE";
}

function getDocumentBadge(document: WorkspaceApplicationDocument) {
  return getFileBadge(document.fileName, document.fileType);
}

function currentStoredDocumentVersion(document: StoredDocument) {
  return document.versions.find(
    (version) => version.version === document.currentVersion,
  );
}

function storedDocumentFileName(document: StoredDocument) {
  return currentStoredDocumentVersion(document)?.artifact?.fileName
    ?? `${document.title || "document"}.docx`;
}

function mergeVersions(
  current: StoredDocumentVersion[],
  incoming: StoredDocumentVersion[],
) {
  return Array.from(
    new Map(
      [...current, ...incoming].map((version) => [version.version, version]),
    ).values(),
  );
}

export function ApplicationWorkspace({
  application,
  backLabel = "Applications",
  onBack,
  onDocumentAttached,
}: ApplicationWorkspaceProps) {
  const [storedDocuments, setStoredDocuments] = useState<StoredDocument[]>([]);
  const [jobDocuments, setJobDocuments] = useState<StoredDocument[]>([]);
  const [documentsStatus, setDocumentsStatus] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [documentsError, setDocumentsError] = useState("");
  const [documentsRequest, setDocumentsRequest] = useState(0);
  const [attachingDocumentId, setAttachingDocumentId] = useState("");
  const [loadingVersionsDocumentId, setLoadingVersionsDocumentId] =
    useState("");
  const [preview, setPreview] = useState<{
    documentId: string;
    version: number;
  } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setStoredDocuments([]);
    setJobDocuments([]);
    setPreview(null);
    setDocumentsError("");

    if (!application) {
      setDocumentsStatus("idle");
      return () => controller.abort();
    }

    setDocumentsStatus("loading");
    void fetchApplicationDocuments<StoredDocument>(
      application.id,
      controller.signal,
    )
      .then((attached) => {
        if (controller.signal.aborted) return;
        setStoredDocuments(attached);
        setDocumentsStatus("ready");
      })
      .catch((caught) => {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        setDocumentsStatus("error");
        setDocumentsError(
          caught instanceof Error
            ? caught.message
            : "Saved documents could not be loaded.",
        );
      });
    void fetchJobDocuments<StoredDocument>(
      application.job.id,
      controller.signal,
    )
      .then((forJob) => {
        if (!controller.signal.aborted) setJobDocuments(forJob);
      })
      .catch((caught) => {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        // The attached-document list remains usable if optional attachment
        // suggestions for the vacancy are temporarily unavailable.
      });

    return () => controller.abort();
  }, [application, documentsRequest]);

  const storedDocumentIds = useMemo(
    () => new Set(storedDocuments.map((document) => document.id)),
    [storedDocuments],
  );
  const attachedFiles = useMemo(
    () => application?.documents.filter(
      (document) => !document.artifactId
        || !storedDocumentIds.has(document.artifactId),
    ) ?? [],
    [application, storedDocumentIds],
  );
  const availableJobDocuments = useMemo(
    () => application
      ? jobDocuments.filter(
        (document) => !document.applicationIds.includes(application.id),
      )
      : [],
    [application, jobDocuments],
  );
  const previewDocument = useMemo(() => {
    if (!preview) return null;
    const document = storedDocuments.find(
      (candidate) => candidate.id === preview.documentId,
    );
    return document
      ? { ...document, currentVersion: preview.version }
      : null;
  }, [preview, storedDocuments]);

  const updateStoredDocument = useCallback((updated: StoredDocument) => {
    setStoredDocuments((current) => {
      const existingIndex = current.findIndex(
        (document) => document.id === updated.id,
      );
      if (existingIndex === -1) return [updated, ...current];
      return current.map((document, index) => (
        index === existingIndex ? updated : document
      ));
    });
    setJobDocuments((current) => current.map((document) => (
      document.id === updated.id ? updated : document
    )));
  }, []);

  async function attachStoredDocument(document: StoredDocument) {
    if (!application || attachingDocumentId) return;
    setAttachingDocumentId(document.id);
    setDocumentsError("");
    try {
      const attached = await attachDocument<StoredDocument>(
        document.id,
        application.id,
      );
      updateStoredDocument(attached);
      const version = currentStoredDocumentVersion(attached);
      if (version?.artifact) {
        onDocumentAttached(application.id, {
          artifactId: attached.id,
          title: attached.title,
          fileName: storedDocumentFileName(attached),
          fileType: version.artifact.contentType ?? "application/octet-stream",
          uploadedAt: attached.updatedAt,
          downloadUrl: documentDownloadUrl(attached.id),
        });
      }
    } catch (caught) {
      setDocumentsError(
        caught instanceof Error
          ? caught.message
          : "The document could not be attached.",
      );
    } finally {
      setAttachingDocumentId("");
    }
  }

  async function loadMoreVersions(document: StoredDocument) {
    if (loadingVersionsDocumentId) return;
    setLoadingVersionsDocumentId(document.id);
    setDocumentsError("");
    try {
      const page = await fetchDocumentVersions<StoredDocumentVersion>(
        document.id,
        document.versions.length,
      );
      updateStoredDocument({
        ...document,
        versions: mergeVersions(document.versions, page.items),
        versionsTotal: page.total,
        versionsHasMore:
          document.versions.length + page.items.length < page.total,
      });
    } catch (caught) {
      setDocumentsError(
        caught instanceof Error
          ? caught.message
          : "Version history could not be loaded.",
      );
    } finally {
      setLoadingVersionsDocumentId("");
    }
  }

  if (!application) {
    return (
      <section className="grid min-h-[520px] place-items-center px-5 py-10">
        <div className="max-w-md text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl border border-border bg-[#fff8f1] text-muted">
            <BriefcaseBusiness className="h-5 w-5" />
          </span>
          <h1 className="mt-4 text-xl font-bold text-foreground">
            No application selected
          </h1>
          <p className="mt-2 text-sm leading-6 text-muted">
            Return to your applications and choose one to view its details.
          </p>
          <Button
            type="button"
            variant="ghost"
            onClick={onBack}
            className="mt-5 h-10 rounded-xl border border-border px-4 text-xs font-bold"
          >
            <ArrowLeft className="h-4 w-4" /> {backLabel}
          </Button>
        </div>
      </section>
    );
  }

  const jobUrl = normalizeJobsChJobUrl(
    application.job.applyUrl || application.job.sourceUrl || "",
  );

  return (
    <section className="job-scroll h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-4 py-5 sm:px-6 sm:py-7">
        <Button
          type="button"
          variant="ghost"
          onClick={onBack}
          className="h-9 rounded-xl px-2 text-xs font-bold text-muted hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> {backLabel}
        </Button>

        <article className="workspace-card mt-4 overflow-hidden">
          <header className="border-b border-border px-5 py-5 sm:px-6 sm:py-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <p className="text-[10px] font-black uppercase tracking-[0.14em] text-accent">
                  Application
                </p>
                <h1 className="mt-2 text-2xl font-bold tracking-[-0.02em] text-foreground">
                  {application.job.title}
                </h1>
                <p className="mt-1 text-sm font-semibold text-[#4a4a47]">
                  {application.job.company}
                </p>
              </div>
              <span
                className={cn(
                  "inline-flex w-fit items-center gap-1.5 rounded-full border px-3 py-1.5 text-[10px] font-black uppercase tracking-wide",
                  applicationStatusStyles[application.status],
                )}
              >
                <CircleDot className="h-3.5 w-3.5" />
                {getApplicationStatusLabel(application.status)}
              </span>
            </div>
          </header>

          <div className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.7fr)]">
            <section aria-labelledby="vacancy-details-title">
              <div className="flex items-center gap-2">
                <BriefcaseBusiness className="h-4 w-4 text-accent" />
                <h2
                  id="vacancy-details-title"
                  className="text-sm font-bold text-foreground"
                >
                  Vacancy
                </h2>
              </div>

              <div className="mt-4 flex flex-wrap gap-2 text-[10px] font-semibold text-muted">
                {application.job.location ? (
                  <span className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-[#fff8f1] px-2.5 py-1.5">
                    <MapPin className="h-3.5 w-3.5" />
                    {application.job.location}
                  </span>
                ) : null}
                {application.job.type ? (
                  <span className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-[#fff8f1] px-2.5 py-1.5">
                    <BriefcaseBusiness className="h-3.5 w-3.5" />
                    {application.job.type}
                  </span>
                ) : null}
              </div>

              {application.job.overview ? (
                <p className="mt-4 max-w-3xl text-sm leading-6 text-[#4a4a47]">
                  {application.job.overview}
                </p>
              ) : null}

              {jobUrl ? (
                <a
                  href={jobUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-5 inline-flex h-10 items-center gap-2 rounded-xl border border-border px-3.5 text-xs font-bold text-foreground transition hover:bg-[#fff3e8]"
                >
                  <ExternalLink className="h-4 w-4" /> View vacancy
                </a>
              ) : null}
            </section>

            <section aria-labelledby="application-documents-title">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-accent" />
                  <h2
                    id="application-documents-title"
                    className="text-sm font-bold text-foreground"
                  >
                    Existing documents
                  </h2>
                </div>
                <span className="text-[10px] font-bold text-muted">
                  {attachedFiles.length + storedDocuments.length}
                </span>
              </div>

              {documentsError ? (
                <div
                  role="alert"
                  className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-accent/25 bg-accent/10 px-3 py-2.5 text-[10px] leading-4 text-accent"
                >
                  <span>{documentsError}</span>
                  <button
                    type="button"
                    onClick={() => setDocumentsRequest((current) => current + 1)}
                    className="inline-flex shrink-0 items-center gap-1 font-bold hover:text-foreground"
                  >
                    <RefreshCw className="h-3 w-3" /> Retry
                  </button>
                </div>
              ) : null}

              {documentsStatus === "loading" ? (
                <div className="mt-4 flex items-center gap-2 rounded-xl border border-border px-4 py-3 text-xs text-muted">
                  <LoaderCircle className="h-4 w-4 animate-spin text-accent" />
                  Loading saved documents…
                </div>
              ) : null}

              {attachedFiles.length || storedDocuments.length ? (
                <div className="mt-4 grid gap-2">
                  {attachedFiles.map((document) => (
                    <article
                      key={document.id}
                      className="flex items-center gap-3 rounded-xl border border-border bg-[#fff8f1] p-3"
                    >
                      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border bg-white text-[9px] font-black text-accent">
                        {getDocumentBadge(document)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-bold text-foreground">
                          {document.title || document.fileName}
                        </p>
                        <p className="mt-1 truncate text-[9px] text-muted">
                          {document.fileName}
                          {document.fileSize ? ` · ${document.fileSize}` : ""}
                          {document.uploadedAt
                            ? ` · ${formatApplicationDate(document.uploadedAt)}`
                            : ""}
                        </p>
                      </div>
                      {document.downloadUrl ? (
                        <div className="flex shrink-0 gap-1.5">
                          <a
                            href={document.downloadUrl}
                            target="_blank"
                            rel="noreferrer"
                            aria-label={`Open ${document.title || document.fileName}`}
                            className="grid h-9 w-9 place-items-center rounded-lg border border-border text-muted transition hover:bg-white hover:text-foreground"
                          >
                            <Eye className="h-4 w-4" />
                          </a>
                          <a
                            href={document.downloadUrl}
                            download={document.fileName}
                            aria-label={`Download ${document.title || document.fileName}`}
                            className="grid h-9 w-9 place-items-center rounded-lg border border-border text-muted transition hover:bg-white hover:text-foreground"
                          >
                            <Download className="h-4 w-4" />
                          </a>
                        </div>
                      ) : null}
                    </article>
                  ))}

                  {storedDocuments.map((document) => {
                    const currentVersion = currentStoredDocumentVersion(document);
                    const fileName = storedDocumentFileName(document);
                    const fileType = currentVersion?.artifact?.contentType ?? "";
                    const hasArtifact = Boolean(currentVersion?.hasRenderedArtifact);
                    const versions = [...document.versions].sort(
                      (left, right) => right.version - left.version,
                    );
                    return (
                      <article
                        key={document.id}
                        className="rounded-xl border border-border bg-[#fff8f1] p-3"
                      >
                        <div className="flex items-center gap-3">
                          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border bg-white text-[9px] font-black text-accent">
                            {getFileBadge(fileName, fileType)}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-bold text-foreground">
                              {document.title}
                            </p>
                            <p className="mt-1 truncate text-[9px] text-muted">
                              {fileName} · v{document.currentVersion}
                            </p>
                          </div>
                          {hasArtifact ? (
                            <div className="flex shrink-0 gap-1.5">
                              <button
                                type="button"
                                aria-label={`Open ${document.title}`}
                                onClick={() => setPreview({
                                  documentId: document.id,
                                  version: document.currentVersion,
                                })}
                                className="grid h-9 w-9 place-items-center rounded-lg border border-border text-muted transition hover:bg-white hover:text-foreground"
                              >
                                <Eye className="h-4 w-4" />
                              </button>
                              <a
                                href={documentDownloadUrl(document.id)}
                                download={fileName}
                                aria-label={`Download ${document.title}`}
                                className="grid h-9 w-9 place-items-center rounded-lg border border-border text-muted transition hover:bg-white hover:text-foreground"
                              >
                                <Download className="h-4 w-4" />
                              </a>
                            </div>
                          ) : null}
                        </div>

                        <details className="mt-3 border-t border-border pt-3">
                          <summary className="cursor-pointer text-[10px] font-bold text-muted marker:text-accent">
                            Version history · {document.versionsTotal}
                          </summary>
                          <div className="mt-2 grid gap-1.5">
                            {versions.map((version) => {
                              const versionFileName = version.artifact?.fileName
                                ?? `${document.title}-v${version.version}.docx`;
                              return (
                                <div
                                  key={version.id}
                                  className="flex items-center gap-2 rounded-lg border border-border bg-white px-2.5 py-2"
                                >
                                  <div className="min-w-0 flex-1">
                                    <p className="text-[10px] font-bold text-foreground">
                                      v{version.version}
                                      {version.version === document.currentVersion
                                        ? " · Current"
                                        : ""}
                                    </p>
                                    <p className="mt-0.5 truncate text-[8px] text-muted">
                                      {versionFileName} · {formatApplicationDate(version.createdAt)}
                                    </p>
                                  </div>
                                  {version.hasRenderedArtifact ? (
                                    <>
                                      <button
                                        type="button"
                                        aria-label={`Open ${document.title} version ${version.version}`}
                                        onClick={() => setPreview({
                                          documentId: document.id,
                                          version: version.version,
                                        })}
                                        className="grid h-7 w-7 place-items-center rounded-md border border-border text-muted hover:text-foreground"
                                      >
                                        <Eye className="h-3 w-3" />
                                      </button>
                                      <a
                                        href={documentDownloadUrl(
                                          document.id,
                                          version.version,
                                        )}
                                        download={versionFileName}
                                        aria-label={`Download ${document.title} version ${version.version}`}
                                        className="grid h-7 w-7 place-items-center rounded-md border border-border text-muted hover:text-foreground"
                                      >
                                        <Download className="h-3 w-3" />
                                      </a>
                                    </>
                                  ) : (
                                    <span className="text-[8px] font-bold text-muted">
                                      Unavailable
                                    </span>
                                  )}
                                </div>
                              );
                            })}
                            {document.versionsHasMore ? (
                              <Button
                                type="button"
                                variant="ghost"
                                disabled={loadingVersionsDocumentId === document.id}
                                onClick={() => void loadMoreVersions(document)}
                                className="h-8 rounded-lg border border-border text-[9px] font-bold"
                              >
                                {loadingVersionsDocumentId === document.id ? (
                                  <LoaderCircle className="h-3 w-3 animate-spin" />
                                ) : null}
                                Load older versions
                              </Button>
                            ) : null}
                          </div>
                        </details>
                      </article>
                    );
                  })}
                </div>
              ) : documentsStatus !== "loading" ? (
                <div className="mt-4 rounded-xl border border-dashed border-border px-4 py-8 text-center">
                  <FileText className="mx-auto h-5 w-5 text-muted" />
                  <p className="mt-2 text-xs text-muted">
                    No documents attached yet.
                  </p>
                </div>
              ) : null}

              {availableJobDocuments.length ? (
                <div className="mt-5 border-t border-border pt-4">
                  <p className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.1em] text-muted">
                    <Paperclip className="h-3.5 w-3.5" /> Available for this vacancy
                  </p>
                  <div className="mt-2 grid gap-2">
                    {availableJobDocuments.map((document) => (
                      <div
                        key={document.id}
                        className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-[10px] font-bold text-foreground">
                            {document.title}
                          </p>
                          <p className="mt-0.5 text-[8px] text-muted">
                            v{document.currentVersion}
                          </p>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          disabled={Boolean(attachingDocumentId)}
                          onClick={() => void attachStoredDocument(document)}
                          className="h-8 rounded-lg border border-border px-2.5 text-[9px] font-bold"
                        >
                          {attachingDocumentId === document.id ? (
                            <LoaderCircle className="h-3 w-3 animate-spin" />
                          ) : (
                            <Paperclip className="h-3 w-3" />
                          )}
                          Attach
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {previewDocument ? (
                <div className="mt-5 border-t border-border pt-5">
                  <div className="mb-3 flex justify-end">
                    <button
                      type="button"
                      onClick={() => setPreview(null)}
                      className="text-[10px] font-bold text-muted hover:text-foreground"
                    >
                      Close preview
                    </button>
                  </div>
                  <DocumentPdfPreview
                    document={previewDocument}
                    label={
                      previewDocument.type === "tailored_resume"
                        ? "CV"
                        : "Cover letter"
                    }
                  />
                </div>
              ) : null}
            </section>
          </div>
        </article>
      </div>
    </section>
  );
}
