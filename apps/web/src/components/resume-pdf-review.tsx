"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Columns2,
  Download,
  Eye,
  FileDiff,
  FileText,
  LockKeyhole,
  LoaderCircle,
  RefreshCw,
  ScanSearch,
  Sparkles,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  attachGeneratedDocument,
  downloadGeneratedDocument,
  fetchGeneratedDocument,
  generatedDocumentDownloadUrl,
  generatedResumeRenderUrl,
  renderResumePdf,
  ResumeTemplateUnavailableError,
  resumeTemplateThumbnailUrl,
} from "@/features/applications/api/workspace-client";
import type {
  ResumeTemplate,
  ResumeTemplateId,
} from "@/lib/resume-templates";
import {
  resumeArtifactGenerationMode,
  resumeRenderSource,
} from "@/lib/resume-generation";
import { cn } from "@/lib/utils";

export type { ResumeTemplate, ResumeTemplateId } from "@/lib/resume-templates";

type AtsSkippedSection = {
  section: string;
  reason: string;
  action: string;
};

type ResumeBullet = {
  id?: string;
  text?: string;
};

type ResumeExperience = {
  id?: string;
  masterExperienceId?: string;
  company?: string;
  title?: string;
  bullets?: ResumeBullet[];
};

type ResumeStageResults = {
  generationMode?: "recruiter_xyz_ats" | "imaginator";
  experienceRewrite?: {
    experiences?: ResumeExperience[];
  };
  atsFinalReview?: {
    atsScan?: {
      skippedSections?: AtsSkippedSection[];
    };
    finalResume?: {
      experiences?: ResumeExperience[];
    };
  };
  claimLedger?: Array<{
    path?: string;
    text?: string;
    origin?: "locked_source" | "synthetic";
    evidenceIds?: string[];
  }>;
  protectedFactsAudit?: {
    passed?: boolean;
    auditedClaimCount?: number;
    promptVersion?: string;
    model?: string;
  };
};

export type ResumePdfArtifact = {
  fileName: string;
  contentType: string;
  templateId?: string | null;
  templateVersion?: string | null;
  sourceAtsFinalReviewId?: string | null;
  sourceImaginatorResumeId?: string | null;
  finalResumeJson?: Record<string, unknown> | null;
  stageResults?: ResumeStageResults | null;
  provenance?: Record<string, unknown> | null;
};

export type ResumePdfDocumentVersion = {
  id: string;
  version: number;
  content: string;
  createdAt: string;
  hasRenderedDocx?: boolean;
  hasRenderedArtifact?: boolean;
  artifact?: ResumePdfArtifact | null;
  factualValidation: Record<string, unknown>;
  visualValidation: Record<string, unknown>;
  diff: Array<{
    blockId: string;
    spanId?: string;
    type: string;
    original: string;
    replacement: string;
    reason: string;
  }>;
};

export type ResumePdfDocument = {
  id: string;
  type: "cover_letter" | "tailored_resume";
  title: string;
  currentVersion: number;
  versions: ResumePdfDocumentVersion[];
};

function currentVersion(document: ResumePdfDocument | null | undefined) {
  return document?.versions.find(
    (version) => version.version === document.currentVersion,
  );
}

function ResumeTemplateThumbnail({ template }: { template: ResumeTemplate }) {
  const thumbnailUrl = resumeTemplateThumbnailUrl(template);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );

  useEffect(() => {
    setStatus("loading");
  }, [thumbnailUrl]);

  return (
    <span
      data-testid={`resume-template-thumbnail-${template.id}`}
      className="relative block aspect-[9/16] w-full overflow-hidden rounded-[5px] border border-slate-300/70 bg-white shadow-[0_8px_24px_rgba(0,0,0,0.3)]"
    >
      {status !== "error" ? (
        <img
          src={thumbnailUrl}
          alt={`${template.name} resume template preview`}
          loading="lazy"
          decoding="async"
          onLoad={() => setStatus("ready")}
          onError={() => setStatus("error")}
          className={cn(
            "h-full w-full object-cover transition-opacity duration-200",
            status === "ready" ? "opacity-100" : "opacity-0",
          )}
        />
      ) : (
        <span className="flex h-full flex-col items-center justify-center gap-1 text-slate-500">
          <FileText className="h-4 w-4" />
          <span className="text-[6px] font-bold uppercase tracking-[0.08em]">
            Preview unavailable
          </span>
        </span>
      )}
      {status === "loading" ? (
        <span
          aria-hidden="true"
          className="absolute inset-0 flex items-center justify-center"
        >
          <LoaderCircle className="h-4 w-4 animate-spin text-slate-500" />
        </span>
      ) : null}
    </span>
  );
}

export function ResumeTemplatePicker({
  templates,
  selectedId,
  onChange,
  notice,
  compact = false,
}: {
  templates: ResumeTemplate[];
  selectedId: ResumeTemplateId;
  onChange: (templateId: ResumeTemplateId) => void;
  notice?: string;
  compact?: boolean;
}) {
  const customTemplates = templates.filter(
    (template) => template.kind === "custom",
  );
  const bundledTemplates = templates.filter(
    (template) => template.kind !== "custom",
  );
  const selectedTemplate =
    templates.find((template) => template.id === selectedId) ?? templates[0];
  const [isTemplateDialogOpen, setIsTemplateDialogOpen] = useState(false);

  useEffect(() => {
    if (!isTemplateDialogOpen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsTemplateDialogOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [isTemplateDialogOpen]);

  function selectCompactTemplate(templateId: ResumeTemplateId) {
    onChange(templateId);
    setIsTemplateDialogOpen(false);
  }

  if (compact) {
    return (
      <>
        <section
          aria-labelledby="resume-template-picker-title"
          className="mt-4 border-t border-border pt-4"
        >
          <div className="grid grid-cols-[76px_minmax(0,1fr)] items-center gap-4">
            <span className="relative block w-full max-w-[9rem]">
              {selectedTemplate ? (
                <ResumeTemplateThumbnail template={selectedTemplate} />
              ) : (
                <span className="block aspect-[9/16] w-full border border-dashed border-border bg-[#fff8f1]" />
              )}
            </span>
            <div className="min-w-0">
              <p
                id="resume-template-picker-title"
                className="text-[9px] font-black uppercase tracking-[0.12em] text-muted"
              >
                Resume template
              </p>
              <p className="mt-2 truncate text-[11px] font-bold text-foreground">
                {selectedTemplate?.name ?? "Select a template"}
              </p>
              <button
                type="button"
                onClick={() => setIsTemplateDialogOpen(true)}
                className="mt-2 border-b border-border pb-0.5 text-[9px] font-bold text-[#1d1e1c] transition hover:border-accent hover:text-foreground"
              >
                Change template
              </button>
            </div>
          </div>
          {notice ? (
            <p role="status" className="mt-3 text-[9px] leading-4 text-accent">
              {notice}
            </p>
          ) : null}
        </section>
        {isTemplateDialogOpen ? (
          <div
            className="fixed inset-0 z-[80] grid place-items-center bg-black/75 p-4 backdrop-blur-sm"
            onMouseDown={(event) => {
              if (event.currentTarget === event.target) {
                setIsTemplateDialogOpen(false);
              }
            }}
          >
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="resume-template-dialog-title"
              aria-describedby="resume-template-dialog-description"
              className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-border bg-white shadow-[6px_8px_36px_rgba(227,214,197,0.72)]"
            >
              <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4 sm:px-6">
                <div>
                  <p className="text-[9px] font-black uppercase tracking-[0.14em] text-accent">
                    Resume appearance
                  </p>
                  <h2 id="resume-template-dialog-title" className="mt-1 text-lg font-bold text-foreground">
                    Choose resume template
                  </h2>
                  <p id="resume-template-dialog-description" className="mt-1 text-[10px] leading-4 text-muted">
                    Select one layout. The chosen template will be used for the next CV generation.
                  </p>
                </div>
                <button
                  type="button"
                  aria-label="Close template selection"
                  onClick={() => setIsTemplateDialogOpen(false)}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-border text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              </header>
              <div className="job-scroll overflow-y-auto px-5 pb-6 sm:px-6">
                {customTemplates.length ? (
                  <TemplatePickerGroup
                    title="My templates"
                    templates={customTemplates}
                    selectedId={selectedId}
                    onChange={selectCompactTemplate}
                  />
                ) : null}
                <TemplatePickerGroup
                  title="Built-in"
                  templates={bundledTemplates}
                  selectedId={selectedId}
                  onChange={selectCompactTemplate}
                />
              </div>
            </section>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <section
      aria-labelledby="resume-template-picker-title"
      className="mt-3 rounded-xl border border-border bg-[#fff8f1] p-3"
    >
      <div className="flex items-center justify-between gap-3">
        <p
          id="resume-template-picker-title"
          className="text-[9px] font-black uppercase tracking-[0.1em] text-muted"
        >
          Resume template
        </p>
        <Columns2 className="h-4 w-4 shrink-0 text-accent" />
      </div>
      <select
        aria-label="Resume template"
        value={selectedId}
        onChange={(event) => onChange(event.target.value as ResumeTemplateId)}
        className="sr-only"
      >
        {customTemplates.length ? (
          <optgroup label="My templates">
            {customTemplates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}
              </option>
            ))}
          </optgroup>
        ) : null}
        <optgroup label="Built-in">
          {bundledTemplates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.name}
            </option>
          ))}
        </optgroup>
      </select>
      {customTemplates.length ? (
        <TemplatePickerGroup
          title="My templates"
          templates={customTemplates}
          selectedId={selectedId}
          onChange={onChange}
        />
      ) : null}
      <TemplatePickerGroup
        title="Built-in"
        templates={bundledTemplates}
        selectedId={selectedId}
        onChange={onChange}
      />
      {notice ? (
        <p
          role="status"
          className="mt-3 rounded-lg border border-accent/25 bg-accent/10 px-2.5 py-2 text-[9px] leading-4 text-accent"
        >
          {notice}
        </p>
      ) : null}
    </section>
  );
}

function TemplatePickerGroup({
  title,
  templates,
  selectedId,
  onChange,
}: {
  title: string;
  templates: ResumeTemplate[];
  selectedId: ResumeTemplateId;
  onChange: (templateId: ResumeTemplateId) => void;
}) {
  if (!templates.length) return null;
  return (
    <div className="mt-3">
      <p className="mb-1.5 text-[8px] font-black uppercase tracking-[0.12em] text-muted">
        {title}
      </p>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(144px,160px))] gap-2">
        {templates.map((template) => {
          const isSelected = template.id === selectedId;
          return (
            <button
              key={template.id}
              type="button"
              aria-pressed={isSelected}
              aria-label={`Use ${template.name} resume template`}
              onClick={() => onChange(template.id)}
              className={cn(
                "group min-w-0 rounded-lg border p-2 text-center transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
                isSelected
                  ? "border-accent/55 bg-accent/[0.08] shadow-[0_0_0_1px_rgba(255,90,0,0.08)]"
                  : "border-border bg-black/15 hover:border-[#c0bbb6] hover:bg-[#fff3e8]",
              )}
            >
              <span className="relative mx-auto block w-full max-w-[9rem]">
                <ResumeTemplateThumbnail template={template} />
                {isSelected ? (
                  <span className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full border border-accent/50 bg-[#ffffff] shadow-lg">
                    <Check className="h-3 w-3 text-accent" />
                  </span>
                ) : null}
              </span>
              <span className="mt-2.5 flex min-h-8 items-start justify-center text-[10px] font-bold leading-4 text-foreground">
                <span className="line-clamp-2">{template.name}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function atsChanges(stageResults: ResumeStageResults | null | undefined) {
  const rewritten = stageResults?.experienceRewrite?.experiences ?? [];
  const finalExperiences = stageResults?.atsFinalReview?.finalResume?.experiences ?? [];
  const rewrittenBullets = new Map<string, { text: string; experience: string }>();

  for (const experience of rewritten) {
    for (const bullet of experience.bullets ?? []) {
      if (!bullet.id) continue;
      rewrittenBullets.set(bullet.id, {
        text: bullet.text ?? "",
        experience: experience.company ?? experience.title ?? "Experience",
      });
    }
  }

  return finalExperiences.flatMap((experience) =>
    (experience.bullets ?? []).flatMap((bullet) => {
      if (!bullet.id) return [];
      const original = rewrittenBullets.get(bullet.id);
      const replacement = bullet.text ?? "";
      if (!original || original.text === replacement) return [];
      return [{
        id: bullet.id,
        experience: experience.company ?? experience.title ?? original.experience,
        original: original.text,
        replacement,
      }];
    }),
  );
}

function provenanceValue(
  provenance: Record<string, unknown> | null | undefined,
  key: string,
): string | number | null {
  const value = provenance?.[key];
  return typeof value === "string" || typeof value === "number"
    ? value
    : null;
}

export function ResumePdfReview({
  applicationId,
  document,
  templates,
  selectedTemplateId,
  onDocumentReady,
  onTemplateUnavailable,
}: {
  applicationId: string;
  document: ResumePdfDocument | null | undefined;
  templates: ResumeTemplate[];
  selectedTemplateId: ResumeTemplateId;
  onDocumentReady: (document: ResumePdfDocument) => void;
  onTemplateUnavailable?: (templateId: ResumeTemplateId) => void;
}) {
  const initialVersion = currentVersion(document);
  const initialArtifact = initialVersion?.artifact;
  const hasPdf = initialArtifact?.contentType === "application/pdf";
  const [activeDocument, setActiveDocument] = useState<ResumePdfDocument | null>(
    hasPdf && document ? document : null,
  );
  const [previewUrl, setPreviewUrl] = useState("");
  const previewUrlRef = useRef("");
  const [status, setStatus] = useState<"idle" | "loading" | "rendering" | "ready" | "error">(
    hasPdf ? "loading" : "idle",
  );
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<"overview" | "details">(
    "overview",
  );

  const activeVersion = currentVersion(activeDocument);
  const artifact = activeVersion?.artifact;
  const stageResults = artifact?.stageResults;
  const generationMode = resumeArtifactGenerationMode(artifact);
  const isImaginator = generationMode === "imaginator";
  const renderSource = resumeRenderSource(artifact);
  const skippedSections = stageResults?.atsFinalReview?.atsScan?.skippedSections ?? [];
  const stageDiff = useMemo(() => atsChanges(stageResults), [stageResults]);
  const syntheticClaims = (stageResults?.claimLedger ?? []).filter(
    (claim) => claim.origin === "synthetic",
  );
  const lockedClaims = (stageResults?.claimLedger ?? []).filter(
    (claim) => claim.origin === "locked_source",
  );
  const protectedFactsAudit = stageResults?.protectedFactsAudit;
  const syntheticClaimCount =
    provenanceValue(artifact?.provenance, "syntheticClaimCount")
    ?? syntheticClaims.length;
  const lockedClaimCount =
    provenanceValue(artifact?.provenance, "lockedClaimCount")
    ?? lockedClaims.length;
  const sourceMasterResumeVersion =
    provenanceValue(artifact?.provenance, "resumeMasterVersionId");
  const constraintsVersion =
    provenanceValue(
      artifact?.provenance,
      "imaginatorConstraintsVersion",
    );
  const legacyDiff = activeVersion?.diff ?? [];
  const selectedTemplate = templates.find(
    (template) => template.id === selectedTemplateId,
  );
  const artifactTemplate = templates.find(
    (template) => template.id === artifact?.templateId,
  );
  const needsRender = Boolean(
    artifact?.templateId &&
      (
        artifact.templateId !== selectedTemplateId ||
        (
          selectedTemplate?.kind === "custom" &&
          selectedTemplate.version != null &&
          artifact.templateVersion !== String(selectedTemplate.version)
        )
      ),
  );

  function replacePreviewUrl(blob: Blob) {
    if (previewUrlRef.current && typeof URL.revokeObjectURL === "function") {
      URL.revokeObjectURL(previewUrlRef.current);
    }
    const nextUrl = typeof URL.createObjectURL === "function"
      ? URL.createObjectURL(blob)
      : "";
    previewUrlRef.current = nextUrl;
    setPreviewUrl(nextUrl);
  }

  useEffect(() => {
    if (!document || !hasPdf) {
      setActiveDocument(null);
      setPreviewUrl("");
      setStatus("idle");
      return;
    }

    const controller = new AbortController();
    setStatus("loading");
    setError("");

    async function loadStoredArtifact() {
      const [detail, blob] = await Promise.all([
        fetchGeneratedDocument<ResumePdfDocument>(
          document!.id,
          controller.signal,
        ),
        downloadGeneratedDocument(
          document!.id,
          document!.currentVersion,
          controller.signal,
        ),
      ]);
      setActiveDocument(detail);
      replacePreviewUrl(blob);
      setStatus("ready");
    }

    void loadStoredArtifact().catch((caught) => {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "The PDF preview could not be loaded.");
    });

    return () => {
      controller.abort();
      if (previewUrlRef.current && typeof URL.revokeObjectURL === "function") {
        URL.revokeObjectURL(previewUrlRef.current);
      }
      previewUrlRef.current = "";
    };
    // replacePreviewUrl only reads stable browser globals and state setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [document?.id, document?.currentVersion, hasPdf]);

  async function renderSelectedTemplate() {
    if (!renderSource) {
      setStatus("error");
      setError("This saved resume does not contain a reusable render source.");
      return;
    }

    setStatus("rendering");
    setError("");
    try {
      const rendered = await renderResumePdf(renderSource, selectedTemplateId);
      const documentId = rendered.documentId;
      if (!documentId) throw new Error("The renderer did not return a saved document ID.");
      const detail = await attachGeneratedDocument<ResumePdfDocument>(
        documentId,
        applicationId,
      );
      replacePreviewUrl(rendered.data);
      setActiveDocument(detail);
      setStatus("ready");
      onDocumentReady(detail);
    } catch (caught) {
      if (caught instanceof ResumeTemplateUnavailableError) {
        onTemplateUnavailable?.(selectedTemplateId);
      }
      setStatus("error");
      setError(
        caught instanceof ResumeTemplateUnavailableError
          ? "This resume template was deleted or is no longer available. Choose another template."
          : caught instanceof Error
            ? caught.message
            : "The PDF could not be rendered.",
      );
    }
  }

  if (!hasPdf && !activeDocument) return null;

  const downloadHref = activeDocument
    ? generatedDocumentDownloadUrl(activeDocument.id)
    : "";
  const downloadName = artifact?.fileName ?? "resume.pdf";
  const docxHref = renderSource
    ? generatedResumeRenderUrl(
      renderSource,
      "docx",
      artifact?.templateId ?? selectedTemplateId,
    )
    : "";
  const docxName = downloadName.toLowerCase().endsWith(".pdf")
    ? `${downloadName.slice(0, -4)}.docx`
    : "resume.docx";
  const confirmImaginatorDownload = (
    event: React.MouseEvent<HTMLAnchorElement>,
  ) => {
    if (
      isImaginator
      && !window.confirm(
        "This Imaginator draft contains AI-invented claims. Review every claim before using it. Download anyway?",
      )
    ) {
      event.preventDefault();
    }
  };

  return (
    <section
      aria-labelledby="resume-pdf-review-title"
      className="mt-5 overflow-hidden rounded-2xl border border-border bg-black/15"
    >
      <div className="flex flex-col gap-3 border-b border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-[9px] font-black uppercase tracking-[0.12em] text-accent">
            PDF review
          </p>
          <h3 id="resume-pdf-review-title" className="mt-1 text-sm font-bold text-foreground">
            Preview the exact submission artifact
          </h3>
          <p className="mt-1 text-[10px] leading-4 text-muted">
            {artifactTemplate?.name ??
              (artifact?.templateId
                ? "Unavailable historical template"
                : "Resume template")}
            {artifact?.templateVersion ? ` · v${artifact.templateVersion}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {needsRender ? (
            <Button
              type="button"
              disabled={status === "rendering" || !renderSource}
              onClick={() => void renderSelectedTemplate()}
              className="h-9 rounded-lg bg-accent px-3 text-[10px] font-bold text-foreground hover:bg-[#e95300] disabled:opacity-45"
            >
              {status === "rendering" ? (
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {status === "rendering"
                ? "Rendering…"
                : `Render ${selectedTemplate?.name ?? "template"}`}
            </Button>
          ) : null}
          {downloadHref ? (
            <a
              href={downloadHref}
              download={downloadName}
              onClick={confirmImaginatorDownload}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-[10px] font-bold text-foreground transition hover:bg-[#fff3e8]"
            >
              <Download className="h-3.5 w-3.5" />
              Download PDF
            </a>
          ) : null}
          {docxHref ? (
            <a
              href={docxHref}
              download={docxName}
              onClick={confirmImaginatorDownload}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-[10px] font-bold text-foreground transition hover:bg-[#fff3e8]"
            >
              <FileText className="h-3.5 w-3.5" />
              Download DOCX
            </a>
          ) : null}
        </div>
      </div>
      {isImaginator ? (
        <div
          role="alert"
          className="flex items-start gap-2 border-b border-accent/25 bg-accent/10 px-4 py-3 text-accent"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="text-[10px] font-bold">
              Imaginator draft · contains AI-invented claims
            </p>
            <p className="mt-1 text-[9px] leading-4 text-accent">
              Employer names, education and candidate identity are locked. Review
              every generated claim before using this document.
            </p>
          </div>
        </div>
      ) : null}
      {error ? (
        <div role="alert" className="border-b border-accent/25 bg-accent/10 px-4 py-3 text-[10px] text-accent">
          {error}
        </div>
      ) : null}
      <div className="grid lg:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.75fr)]">
        <div className="min-h-[520px] border-b border-border bg-[#ffffff] p-3 lg:border-b-0 lg:border-r">
          {status === "loading" || status === "rendering" ? (
            <div className="grid h-[496px] place-items-center text-center">
              <div>
                <LoaderCircle className="mx-auto h-6 w-6 animate-spin text-accent" />
                <p className="mt-2 text-[10px] font-bold text-muted">
                  {status === "rendering" ? "Rendering and validating PDF…" : "Loading saved PDF…"}
                </p>
              </div>
            </div>
          ) : previewUrl ? (
            <iframe
              title="Resume PDF preview"
              src={previewUrl}
              className="h-[496px] w-full rounded-lg border border-border bg-white"
            />
          ) : (
            <div className="grid h-[496px] place-items-center rounded-lg border border-dashed border-border text-center">
              <div>
                <Eye className="mx-auto h-6 w-6 text-muted" />
                <p className="mt-2 text-[10px] font-bold text-muted">
                  Open or download the saved PDF to inspect it.
                </p>
              </div>
            </div>
          )}
        </div>
        <div className="min-w-0">
          <div role="tablist" aria-label="Resume PDF review details" className="grid grid-cols-2 border-b border-border p-1.5">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "overview"}
              onClick={() => setActiveTab("overview")}
              className={cn(
                "inline-flex h-9 items-center justify-center gap-1.5 rounded-lg text-[10px] font-bold transition",
                activeTab === "overview" ? "bg-[#fff8f1] text-foreground" : "text-muted hover:text-foreground",
              )}
            >
              {isImaginator ? (
                <Sparkles className="h-3.5 w-3.5" />
              ) : (
                <ScanSearch className="h-3.5 w-3.5" />
              )}
              {isImaginator
                ? `Invented claims · ${syntheticClaimCount}`
                : "ATS scan"}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "details"}
              onClick={() => setActiveTab("details")}
              className={cn(
                "inline-flex h-9 items-center justify-center gap-1.5 rounded-lg text-[10px] font-bold transition",
                activeTab === "details" ? "bg-[#fff8f1] text-foreground" : "text-muted hover:text-foreground",
              )}
            >
              {isImaginator ? (
                <LockKeyhole className="h-3.5 w-3.5" />
              ) : (
                <FileDiff className="h-3.5 w-3.5" />
              )}
              {isImaginator
                ? "Provenance"
                : `Diff · ${stageDiff.length || legacyDiff.length}`}
            </button>
          </div>
          <div className="job-scroll h-[476px] overflow-y-auto p-3">
            {isImaginator && activeTab === "overview" ? (
              syntheticClaims.length ? (
                <div className="space-y-2">
                  {syntheticClaims.map((claim, index) => (
                    <article
                      key={`${claim.path ?? "claim"}-${index}`}
                      className="rounded-lg border border-accent/25 bg-accent/10 p-3"
                    >
                      <p className="text-[8px] font-black uppercase tracking-wide text-accent">
                        {claim.path || `Generated claim ${index + 1}`}
                      </p>
                      <p className="mt-2 text-[10px] leading-4 text-[#1d1e1c]">
                        {claim.text || "Generated claim details unavailable"}
                      </p>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-accent/25 bg-accent/10 p-3">
                  <p className="text-[10px] font-bold text-accent">
                    Synthetic claim details are unavailable.
                  </p>
                </div>
              )
            ) : isImaginator ? (
              <div className="space-y-2">
                <article className="rounded-lg border border-border bg-[#fff8f1] p-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-bold text-foreground">
                    <LockKeyhole className="h-3.5 w-3.5 text-success" />
                    Locked source facts
                  </p>
                  <dl className="mt-3 space-y-2 text-[9px] leading-4 text-muted">
                    <div className="flex justify-between gap-3">
                      <dt>Locked claims</dt>
                      <dd className="font-mono text-foreground">{lockedClaimCount}</dd>
                    </div>
                    <div className="flex justify-between gap-3">
                      <dt>Synthetic claims</dt>
                      <dd className="font-mono text-accent">{syntheticClaimCount}</dd>
                    </div>
                    {protectedFactsAudit ? (
                      <div className="flex justify-between gap-3">
                        <dt>Protected-fact audit</dt>
                        <dd className="text-right font-mono text-success">
                          {protectedFactsAudit.passed ? "Passed" : "Unavailable"}
                          {typeof protectedFactsAudit.auditedClaimCount === "number"
                            ? ` · ${protectedFactsAudit.auditedClaimCount} claims`
                            : ""}
                        </dd>
                      </div>
                    ) : null}
                    {sourceMasterResumeVersion ? (
                      <div className="flex justify-between gap-3">
                        <dt>Master Resume version</dt>
                        <dd className="break-all font-mono text-foreground">
                          {sourceMasterResumeVersion}
                        </dd>
                      </div>
                    ) : null}
                    {constraintsVersion ? (
                      <div className="flex justify-between gap-3">
                        <dt>Constraints</dt>
                        <dd className="break-all font-mono text-foreground">
                          {constraintsVersion}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                </article>
                <p className="px-1 text-[9px] leading-4 text-muted">
                  Employer names, education and candidate identity were copied
                  from the locked Master Resume by the server.
                </p>
              </div>
            ) : activeTab === "overview" ? (
              skippedSections.length ? (
                <div className="space-y-2">
                  {skippedSections.map((item) => (
                    <article key={item.section} className="rounded-lg border border-accent/25 bg-accent/10 p-3">
                      <p className="text-[9px] font-black uppercase tracking-wide text-accent">
                        {item.section}
                      </p>
                      <p className="mt-2 text-[10px] leading-4 text-[#1d1e1c]">{item.reason}</p>
                      <p className="mt-2 border-t border-border pt-2 text-[9px] leading-4 text-muted">
                        <strong className="text-foreground">Action:</strong> {item.action}
                      </p>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-success/20 bg-success/[0.045] p-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-bold text-success">
                    <Check className="h-3.5 w-3.5" />
                    No skipped sections
                  </p>
                  <p className="mt-1 text-[9px] leading-4 text-muted">
                    The final ATS scan did not flag a section as likely to be skipped.
                  </p>
                </div>
              )
            ) : stageDiff.length ? (
              <div className="space-y-2">
                {stageDiff.map((change) => (
                  <article key={change.id} className="rounded-lg border border-border bg-[#fff8f1] p-3">
                    <p className="text-[8px] font-black uppercase tracking-wide text-muted">
                      {change.experience} · {change.id}
                    </p>
                    <p className="mt-2 text-[10px] leading-4 text-accent line-through">
                      {change.original}
                    </p>
                    <p className="mt-1 text-[10px] leading-4 text-accent">
                      {change.replacement}
                    </p>
                  </article>
                ))}
              </div>
            ) : legacyDiff.length ? (
              <div className="space-y-2">
                {legacyDiff.map((change) => (
                  <article key={`${change.blockId}-${change.spanId ?? change.original}`} className="rounded-lg border border-border bg-[#fff8f1] p-3">
                    <p className="text-[8px] font-black uppercase tracking-wide text-muted">
                      {change.blockId}{change.spanId ? ` · ${change.spanId}` : ""}
                    </p>
                    <p className="mt-2 text-[10px] leading-4 text-accent line-through">{change.original}</p>
                    <p className="mt-1 text-[10px] leading-4 text-accent">{change.replacement}</p>
                    <p className="mt-2 text-[9px] leading-4 text-muted">{change.reason}</p>
                  </article>
                ))}
              </div>
            ) : (
              <div className="rounded-lg border border-success/20 bg-success/[0.045] p-3">
                <p className="flex items-center gap-1.5 text-[10px] font-bold text-success">
                  <FileText className="h-3.5 w-3.5" />
                  No ATS-stage wording changes
                </p>
                <p className="mt-1 text-[9px] leading-4 text-muted">
                  The ATS final review kept the experience rewrite unchanged.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
