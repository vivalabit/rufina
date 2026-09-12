"use client";

import {
  ArrowLeft,
  BriefcaseBusiness,
  CircleDot,
  Download,
  ExternalLink,
  FileText,
  MapPin,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  formatApplicationDate,
  getApplicationStatusLabel,
} from "@/features/applications/formatting";
import { applicationStatusStyles } from "@/features/applications/model/constants";
import { normalizeJobsChJobUrl } from "@/lib/job-url";
import { cn } from "@/lib/utils";
import type { ApplicationStatus } from "@/shared/types/application";

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

type WorkspaceApplication = {
  id: string;
  status: ApplicationStatus;
  nextStep: string;
  notes: string;
  job: {
    id: string;
    title: string;
    company: string;
    location: string;
    type: string;
    match: number;
    overview: string;
    responsibilities: string[];
    requirements: string[];
    skills: string[];
    applyUrl?: string;
    sourceUrl?: string;
    aiMatch?: {
      version?: string;
      revision?: string;
      fingerprint?: string;
      reasons: string[];
      gaps: string[];
      updatedAt?: string;
      applicationGuide?: {
        language: "English" | "German";
        positioning: string;
        [key: string]: unknown;
      };
    };
  };
  documents: WorkspaceApplicationDocument[];
};

type WorkspaceProfile = {
  name: string;
  current_role: string;
  desired_role: string;
  location: string;
  headline: string;
  skills: string;
  experience: string;
  education: string;
  documents: string;
  resume_file_name: string;
  resume_file_size: string;
  resume_updated_at: string;
};

type ApplicationWorkspaceProps = {
  application: WorkspaceApplication | null;
  profile: WorkspaceProfile;
  backLabel?: string;
  onBack: () => void;
  onOpenAssistant: (prompt: string, applicationId: string) => void;
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
  onMarkApplied: (applicationId: string) => void;
  onRefreshAnalysis: (applicationId: string) => void;
  isAnalysisRefreshing: boolean;
};

function getDocumentBadge(document: WorkspaceApplicationDocument) {
  const extension = document.fileName.split(".").pop()?.trim().toUpperCase();
  if (extension && extension.length <= 5) return extension;
  if (document.fileType.includes("pdf")) return "PDF";
  if (document.fileType.includes("word")) return "DOC";
  return "FILE";
}

export function ApplicationWorkspace({
  application,
  backLabel = "Applications",
  onBack,
}: ApplicationWorkspaceProps) {
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
                  {application.documents.length}
                </span>
              </div>

              {application.documents.length ? (
                <div className="mt-4 grid gap-2">
                  {application.documents.map((document) => (
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
                        <a
                          href={document.downloadUrl}
                          download={document.fileName}
                          aria-label={`Download ${document.title || document.fileName}`}
                          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border text-muted transition hover:bg-white hover:text-foreground"
                        >
                          <Download className="h-4 w-4" />
                        </a>
                      ) : null}
                    </article>
                  ))}
                </div>
              ) : (
                <div className="mt-4 rounded-xl border border-dashed border-border px-4 py-8 text-center">
                  <FileText className="mx-auto h-5 w-5 text-muted" />
                  <p className="mt-2 text-xs text-muted">
                    No documents attached yet.
                  </p>
                </div>
              )}
            </section>
          </div>
        </article>
      </div>
    </section>
  );
}
