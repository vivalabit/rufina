"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  Columns2,
  Download,
  Eye,
  FileDiff,
  FileText,
  LoaderCircle,
  Palette,
  RefreshCw,
  ScanSearch,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { fetchWithTimeout } from "@/lib/api-client";
import { cn } from "@/lib/utils";

export type ResumeTemplateId =
  | "classic_single"
  | "modern_single"
  | "modern_two_column";

export type BundledResumeTemplate = {
  id: ResumeTemplateId;
  name: string;
  description: string;
  layout: "single_column" | "two_column";
  columns: 1 | 2;
};

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
};

export type ResumePdfArtifact = {
  fileName: string;
  contentType: string;
  templateId?: string | null;
  templateVersion?: string | null;
  sourceAtsFinalReviewId?: string | null;
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

const templateTheme: Record<
  ResumeTemplateId,
  {
    accentName: string;
    accentClass: string;
    previewClass: string;
  }
> = {
  classic_single: {
    accentName: "Neutral",
    accentClass: "bg-[#2b2b2b]",
    previewClass: "border-[#d7d2c8] bg-[#f7f4ee]",
  },
  modern_single: {
    accentName: "Teal",
    accentClass: "bg-[#176b87]",
    previewClass: "border-[#bcd6dc] bg-[#f3f8f8]",
  },
  modern_two_column: {
    accentName: "Navy",
    accentClass: "bg-[#243b53]",
    previewClass: "border-[#b9c5d1] bg-[#f3f6f8]",
  },
};

function currentVersion(document: ResumePdfDocument | null | undefined) {
  return document?.versions.find(
    (version) => version.version === document.currentVersion,
  );
}

function templatePreview(template: BundledResumeTemplate) {
  const theme = templateTheme[template.id];
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative block h-24 overflow-hidden rounded-md border p-2 shadow-inner",
        theme.previewClass,
      )}
    >
      <span className={cn("block h-2 w-2/3 rounded-sm", theme.accentClass)} />
      <span className="mt-1 block h-1 w-1/2 rounded-sm bg-slate-400/65" />
      {template.columns === 2 ? (
        <span className="mt-3 grid grid-cols-[0.72fr_1.28fr] gap-1.5">
          <span className="space-y-1 rounded-sm bg-slate-300/45 p-1">
            <span className="block h-1 rounded-sm bg-slate-500/60" />
            <span className="block h-1 rounded-sm bg-slate-400/50" />
            <span className="block h-1 w-4/5 rounded-sm bg-slate-400/50" />
            <span className="block h-1 rounded-sm bg-slate-400/50" />
          </span>
          <span className="space-y-1">
            <span className={cn("block h-1 rounded-sm", theme.accentClass)} />
            <span className="block h-1 rounded-sm bg-slate-400/50" />
            <span className="block h-1 rounded-sm bg-slate-400/50" />
            <span className="block h-1 w-4/5 rounded-sm bg-slate-400/50" />
          </span>
        </span>
      ) : (
        <span className="mt-3 block space-y-1">
          <span className={cn("block h-1 w-1/3 rounded-sm", theme.accentClass)} />
          <span className="block h-1 rounded-sm bg-slate-400/50" />
          <span className="block h-1 rounded-sm bg-slate-400/50" />
          <span className="block h-1 w-4/5 rounded-sm bg-slate-400/50" />
          <span className={cn("mt-2 block h-1 w-1/3 rounded-sm", theme.accentClass)} />
          <span className="block h-1 rounded-sm bg-slate-400/50" />
        </span>
      )}
    </span>
  );
}

export function ResumeTemplatePicker({
  templates,
  selectedId,
  onChange,
}: {
  templates: BundledResumeTemplate[];
  selectedId: ResumeTemplateId;
  onChange: (templateId: ResumeTemplateId) => void;
}) {
  const selected = templates.find((template) => template.id === selectedId);
  const selectedTheme = selected ? templateTheme[selected.id] : null;

  return (
    <section
      aria-labelledby="resume-template-picker-title"
      className="mt-3 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3"
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p
            id="resume-template-picker-title"
            className="text-[9px] font-black uppercase tracking-[0.1em] text-muted"
          >
            Resume template
          </p>
          <p className="mt-1 text-[9px] leading-4 text-muted">
            Bundled and ATS-safe. Custom HTML, CSS, and DOCX templates are not accepted.
          </p>
        </div>
        <Columns2 className="h-4 w-4 shrink-0 text-accent" />
      </div>
      <select
        aria-label="Resume template"
        value={selectedId}
        onChange={(event) => onChange(event.target.value as ResumeTemplateId)}
        className="sr-only"
      >
        {templates.map((template) => (
          <option key={template.id} value={template.id}>
            {template.name}
          </option>
        ))}
      </select>
      <div className="mt-3 grid grid-cols-3 gap-2">
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
                "rounded-lg border p-1.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
                isSelected
                  ? "border-accent/55 bg-accent/[0.08]"
                  : "border-white/[0.08] bg-black/15 hover:border-white/[0.16]",
              )}
            >
              {templatePreview(template)}
              <span className="mt-1.5 flex items-center gap-1 text-[8px] font-bold leading-3 text-white">
                {isSelected ? <Check className="h-3 w-3 text-accent" /> : null}
                {template.name}
              </span>
            </button>
          );
        })}
      </div>
      {selected && selectedTheme ? (
        <div className="mt-3 rounded-lg border border-white/[0.07] bg-black/15 p-2.5">
          <div className="flex items-center gap-1.5 text-[9px] font-black uppercase tracking-wide text-[#cbd3df]">
            <Palette className="h-3.5 w-3.5 text-accent" />
            Allowed theme
          </div>
          <div className="mt-2 grid grid-cols-2 gap-1.5 text-[8px] sm:grid-cols-4">
            <span className="rounded-md border border-white/[0.07] bg-white/[0.025] px-2 py-1.5 text-muted">
              <strong className="block text-[#e5e9ef]">Accent</strong>
              {selectedTheme.accentName}
            </span>
            <span className="rounded-md border border-white/[0.07] bg-white/[0.025] px-2 py-1.5 text-muted">
              <strong className="block text-[#e5e9ef]">Mode</strong>
              Light
            </span>
            <span className="rounded-md border border-white/[0.07] bg-white/[0.025] px-2 py-1.5 text-muted">
              <strong className="block text-[#e5e9ef]">Page</strong>
              A4
            </span>
            <span className="rounded-md border border-white/[0.07] bg-white/[0.025] px-2 py-1.5 text-muted">
              <strong className="block text-[#e5e9ef]">Layout</strong>
              {selected.columns === 2 ? "Two column" : "Single column"}
            </span>
          </div>
          <p className="mt-2 text-[9px] leading-4 text-muted">{selected.description}</p>
        </div>
      ) : null}
    </section>
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

export function ResumePdfReview({
  apiBaseUrl,
  document,
  templates,
  selectedTemplateId,
  onDocumentReady,
}: {
  apiBaseUrl: string;
  document: ResumePdfDocument | null | undefined;
  templates: BundledResumeTemplate[];
  selectedTemplateId: ResumeTemplateId;
  onDocumentReady: (document: ResumePdfDocument) => void;
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
  const [activeTab, setActiveTab] = useState<"ats" | "diff">("ats");

  const activeVersion = currentVersion(activeDocument);
  const artifact = activeVersion?.artifact;
  const stageResults = artifact?.stageResults;
  const skippedSections = stageResults?.atsFinalReview?.atsScan?.skippedSections ?? [];
  const stageDiff = useMemo(() => atsChanges(stageResults), [stageResults]);
  const legacyDiff = activeVersion?.diff ?? [];
  const selectedTemplate = templates.find(
    (template) => template.id === selectedTemplateId,
  );
  const needsRender = Boolean(
    artifact?.templateId && artifact.templateId !== selectedTemplateId,
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
      const [detailResponse, pdfResponse] = await Promise.all([
        fetchWithTimeout(
          `${apiBaseUrl}/documents/${encodeURIComponent(document!.id)}`,
          { cache: "no-store", signal: controller.signal },
        ),
        fetchWithTimeout(
          `${apiBaseUrl}/documents/${encodeURIComponent(document!.id)}/download?version=${document!.currentVersion}`,
          { cache: "no-store", signal: controller.signal },
        ),
      ]);
      if (!detailResponse.ok || !pdfResponse.ok) {
        throw new Error("The saved PDF preview is temporarily unavailable.");
      }
      const detail = await detailResponse.json() as ResumePdfDocument;
      const blob = await pdfResponse.blob();
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
  }, [apiBaseUrl, document?.id, document?.currentVersion, hasPdf]);

  async function renderSelectedTemplate() {
    const reviewId = artifact?.sourceAtsFinalReviewId;
    if (!reviewId) {
      setStatus("error");
      setError("This saved resume does not contain an ATS final review ID.");
      return;
    }

    setStatus("rendering");
    setError("");
    try {
      const response = await fetchWithTimeout(
        `${apiBaseUrl}/resume-tailoring/ats-final-review/${encodeURIComponent(reviewId)}/pdf?templateId=${encodeURIComponent(selectedTemplateId)}`,
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error("The selected PDF template could not be rendered.");
      const documentId = response.headers.get("X-Rufina-Document-Id");
      if (!documentId) throw new Error("The renderer did not return a saved document ID.");
      const blob = await response.blob();
      const detailResponse = await fetchWithTimeout(
        `${apiBaseUrl}/documents/${encodeURIComponent(documentId)}`,
        { cache: "no-store" },
      );
      if (!detailResponse.ok) throw new Error("The rendered PDF details could not be loaded.");
      const detail = await detailResponse.json() as ResumePdfDocument;
      replacePreviewUrl(blob);
      setActiveDocument(detail);
      setStatus("ready");
      onDocumentReady(detail);
    } catch (caught) {
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "The PDF could not be rendered.");
    }
  }

  if (!hasPdf && !activeDocument) return null;

  const downloadHref = activeDocument
    ? `${apiBaseUrl}/documents/${encodeURIComponent(activeDocument.id)}/download`
    : "";
  const downloadName = artifact?.fileName ?? "resume.pdf";

  return (
    <section
      aria-labelledby="resume-pdf-review-title"
      className="mt-5 overflow-hidden rounded-2xl border border-white/[0.08] bg-black/15"
    >
      <div className="flex flex-col gap-3 border-b border-white/[0.07] px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-[9px] font-black uppercase tracking-[0.12em] text-accent">
            PDF review
          </p>
          <h3 id="resume-pdf-review-title" className="mt-1 text-sm font-bold text-white">
            Preview the exact submission artifact
          </h3>
          <p className="mt-1 text-[10px] leading-4 text-muted">
            {artifact?.templateId ?? "Bundled template"}
            {artifact?.templateVersion ? ` · v${artifact.templateVersion}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {needsRender ? (
            <Button
              type="button"
              disabled={status === "rendering" || !artifact?.sourceAtsFinalReviewId}
              onClick={() => void renderSelectedTemplate()}
              className="h-9 rounded-lg bg-accent px-3 text-[10px] font-bold text-white hover:bg-[#ff6a14] disabled:opacity-45"
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
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-white/[0.09] px-3 text-[10px] font-bold text-white transition hover:bg-white/[0.05]"
            >
              <Download className="h-3.5 w-3.5" />
              Download PDF
            </a>
          ) : null}
        </div>
      </div>
      {error ? (
        <div role="alert" className="border-b border-red-400/20 bg-red-500/[0.06] px-4 py-3 text-[10px] text-red-200">
          {error}
        </div>
      ) : null}
      <div className="grid lg:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.75fr)]">
        <div className="min-h-[520px] border-b border-white/[0.07] bg-[#171b20] p-3 lg:border-b-0 lg:border-r">
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
              className="h-[496px] w-full rounded-lg border border-white/[0.09] bg-white"
            />
          ) : (
            <div className="grid h-[496px] place-items-center rounded-lg border border-dashed border-white/[0.1] text-center">
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
          <div role="tablist" aria-label="Resume PDF review details" className="grid grid-cols-2 border-b border-white/[0.07] p-1.5">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "ats"}
              onClick={() => setActiveTab("ats")}
              className={cn(
                "inline-flex h-9 items-center justify-center gap-1.5 rounded-lg text-[10px] font-bold transition",
                activeTab === "ats" ? "bg-white/[0.09] text-white" : "text-muted hover:text-white",
              )}
            >
              <ScanSearch className="h-3.5 w-3.5" />
              ATS scan
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "diff"}
              onClick={() => setActiveTab("diff")}
              className={cn(
                "inline-flex h-9 items-center justify-center gap-1.5 rounded-lg text-[10px] font-bold transition",
                activeTab === "diff" ? "bg-white/[0.09] text-white" : "text-muted hover:text-white",
              )}
            >
              <FileDiff className="h-3.5 w-3.5" />
              Diff · {stageDiff.length || legacyDiff.length}
            </button>
          </div>
          <div className="job-scroll h-[476px] overflow-y-auto p-3">
            {activeTab === "ats" ? (
              skippedSections.length ? (
                <div className="space-y-2">
                  {skippedSections.map((item) => (
                    <article key={item.section} className="rounded-lg border border-amber-400/20 bg-amber-400/[0.045] p-3">
                      <p className="text-[9px] font-black uppercase tracking-wide text-amber-200">
                        {item.section}
                      </p>
                      <p className="mt-2 text-[10px] leading-4 text-[#dfe5ec]">{item.reason}</p>
                      <p className="mt-2 border-t border-white/[0.07] pt-2 text-[9px] leading-4 text-muted">
                        <strong className="text-white">Action:</strong> {item.action}
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
                  <article key={change.id} className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                    <p className="text-[8px] font-black uppercase tracking-wide text-muted">
                      {change.experience} · {change.id}
                    </p>
                    <p className="mt-2 text-[10px] leading-4 text-red-200/70 line-through">
                      {change.original}
                    </p>
                    <p className="mt-1 text-[10px] leading-4 text-emerald-200">
                      {change.replacement}
                    </p>
                  </article>
                ))}
              </div>
            ) : legacyDiff.length ? (
              <div className="space-y-2">
                {legacyDiff.map((change) => (
                  <article key={`${change.blockId}-${change.spanId ?? change.original}`} className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3">
                    <p className="text-[8px] font-black uppercase tracking-wide text-muted">
                      {change.blockId}{change.spanId ? ` · ${change.spanId}` : ""}
                    </p>
                    <p className="mt-2 text-[10px] leading-4 text-red-200/70 line-through">{change.original}</p>
                    <p className="mt-1 text-[10px] leading-4 text-emerald-200">{change.replacement}</p>
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
