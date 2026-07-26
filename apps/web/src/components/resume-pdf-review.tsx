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
import type {
  ResumeTemplate,
  ResumeTemplateId,
} from "@/lib/resume-templates";
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

const bundledTemplateTheme: Record<
  string,
  {
    accentName: string;
    accentColor: string;
    previewClass: string;
  }
> = {
  classic_single: {
    accentName: "Neutral",
    accentColor: "#2b2b2b",
    previewClass: "border-[#d7d2c8] bg-[#f7f4ee]",
  },
  modern_single: {
    accentName: "Teal",
    accentColor: "#176b87",
    previewClass: "border-[#bcd6dc] bg-[#f3f8f8]",
  },
  modern_two_column: {
    accentName: "Navy",
    accentColor: "#243b53",
    previewClass: "border-[#b9c5d1] bg-[#f3f6f8]",
  },
  swiss_classic: {
    accentName: "Black",
    accentColor: "#000000",
    previewClass: "border-[#b8b8b8] bg-white",
  },
  swiss_local_german: {
    accentName: "Black",
    accentColor: "#000000",
    previewClass: "border-[#aeb8ae] bg-[#fffefb]",
  },
};

function currentVersion(document: ResumePdfDocument | null | undefined) {
  return document?.versions.find(
    (version) => version.version === document.currentVersion,
  );
}

function visualTheme(template: ResumeTemplate) {
  const bundled = bundledTemplateTheme[template.id];
  if (bundled) return bundled;
  const accentColor = template.designJson?.accentColor || "#64748b";
  return {
    accentName: accentColor.toUpperCase(),
    accentColor,
    previewClass: "border-[#cbd5e1] bg-[#f8fafc]",
  };
}

function templatePreview(template: ResumeTemplate) {
  const theme = visualTheme(template);
  const accentStyle = { backgroundColor: theme.accentColor };
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative block h-24 overflow-hidden rounded-md border p-2 shadow-inner",
        theme.previewClass,
      )}
    >
      <span className="block h-2 w-2/3 rounded-sm" style={accentStyle} />
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
            <span className="block h-1 rounded-sm" style={accentStyle} />
            <span className="block h-1 rounded-sm bg-slate-400/50" />
            <span className="block h-1 rounded-sm bg-slate-400/50" />
            <span className="block h-1 w-4/5 rounded-sm bg-slate-400/50" />
          </span>
        </span>
      ) : (
        <span className="mt-3 block space-y-1">
          <span className="block h-1 w-1/3 rounded-sm" style={accentStyle} />
          <span className="block h-1 rounded-sm bg-slate-400/50" />
          <span className="block h-1 rounded-sm bg-slate-400/50" />
          <span className="block h-1 w-4/5 rounded-sm bg-slate-400/50" />
          <span className="mt-2 block h-1 w-1/3 rounded-sm" style={accentStyle} />
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
  notice,
}: {
  templates: ResumeTemplate[];
  selectedId: ResumeTemplateId;
  onChange: (templateId: ResumeTemplateId) => void;
  notice?: string;
}) {
  const selected = templates.find((template) => template.id === selectedId);
  const selectedTheme = selected ? visualTheme(selected) : null;
  const customTemplates = templates.filter(
    (template) => template.kind === "custom",
  );
  const bundledTemplates = templates.filter(
    (template) => template.kind !== "custom",
  );

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
            Trusted layouts with verified design tokens. User HTML, CSS, and
            DOCX templates are never accepted.
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
          className="mt-3 rounded-lg border border-amber-400/20 bg-amber-400/[0.06] px-2.5 py-2 text-[9px] leading-4 text-amber-100"
        >
          {notice}
        </p>
      ) : null}
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
          <p className="mt-2 text-[9px] font-bold text-[#cbd3df]">
            {selected.kind === "custom"
              ? `Personal template · v${selected.version ?? 1}`
              : "Built-in template"}
          </p>
          <p className="mt-2 text-[9px] leading-4 text-muted">{selected.description}</p>
        </div>
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
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
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
                <span className="truncate">{template.name}</span>
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

export function ResumePdfReview({
  apiBaseUrl,
  applicationId,
  document,
  templates,
  selectedTemplateId,
  onDocumentReady,
  onTemplateUnavailable,
}: {
  apiBaseUrl: string;
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
      if (!response.ok) {
        const detail = await readResumePdfError(
          response,
          "The selected PDF template could not be rendered.",
        );
        if (response.status === 404) {
          onTemplateUnavailable?.(selectedTemplateId);
          throw new Error(
            "This resume template was deleted or is no longer available. Choose another template.",
          );
        }
        throw new Error(detail);
      }
      const documentId = response.headers.get("X-Rufina-Document-Id");
      if (!documentId) throw new Error("The renderer did not return a saved document ID.");
      const blob = await response.blob();
      const detailResponse = await fetchWithTimeout(
        `${apiBaseUrl}/documents/${encodeURIComponent(documentId)}/attachments`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ applicationId }),
        },
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

async function readResumePdfError(
  response: Response,
  fallback: string,
): Promise<string> {
  const payload = await response.json().catch(() => null) as {
    detail?: unknown;
  } | null;
  return typeof payload?.detail === "string" && payload.detail.trim()
    ? payload.detail
    : fallback;
}
