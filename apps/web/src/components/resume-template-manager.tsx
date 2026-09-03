"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Copy,
  FileText,
  FilePlus2,
  LayoutTemplate,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  Upload,
} from "lucide-react";

import { ResumeTemplateEditor } from "@/components/resume-template-editor";
import { ResumeTemplatePreview } from "@/components/resume-template-preview";
import { Button } from "@/components/ui/button";
import {
  deleteResumeTemplate,
  duplicateResumeTemplate,
  exportResumeTemplate,
  fetchResumeTemplates,
  importResumeTemplate,
  saveResumeTemplate,
} from "@/features/profile/api/template-client";
import type {
  ResumeTemplate,
  ResumeTemplateDraft,
} from "@/lib/resume-templates";
import { cn } from "@/lib/utils";
import { apiUnavailableMessage } from "@/shared/api/client";

type ManagerStatus = "loading" | "ready" | "error";
type MutationKind =
  "saving" | "duplicating" | "deleting" | "exporting" | "importing" | null;
type MessageKind = "success" | "error" | null;
const MAX_TEMPLATE_BACKUP_BYTES = 32_000;

export function ResumeTemplateManager() {
  const [templates, setTemplates] = useState<ResumeTemplate[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ResumeTemplateDraft | null>(null);
  const [status, setStatus] = useState<ManagerStatus>("loading");
  const [mutation, setMutation] = useState<MutationKind>(null);
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState<MessageKind>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedId) ?? null,
    [selectedId, templates],
  );
  const bundledTemplates = useMemo(
    () => templates.filter((template) => template.kind === "bundled"),
    [templates],
  );
  const customTemplates = useMemo(
    () => templates.filter((template) => template.kind === "custom"),
    [templates],
  );
  const isDirty = Boolean(
    draft &&
    selectedTemplate &&
    (selectedTemplate.kind === "bundled" ||
      draftSignature(draft) !==
        draftSignature(draftFromTemplate(selectedTemplate))),
  );
  const hasValidAccentColor = Boolean(
    draft && /^#[0-9A-Fa-f]{6}$/.test(draft.designJson.accentColor),
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadTemplates(controller.signal);
    return () => controller.abort();
  }, []);

  async function loadTemplates(signal?: AbortSignal) {
    setStatus("loading");
    setMessage("");
    setMessageKind(null);
    try {
      const nextTemplates = await fetchResumeTemplates(signal);
      if (signal?.aborted) return;
      setTemplates(nextTemplates);
      const preferred =
        nextTemplates.find((template) => template.kind === "custom") ??
        nextTemplates[0] ??
        null;
      setSelectedId(preferred?.id ?? null);
      setDraft(preferred ? draftFromTemplate(preferred) : null);
      setStatus("ready");
    } catch (error) {
      if (signal?.aborted) return;
      setStatus("error");
      setMessageKind("error");
      setMessage(
        apiUnavailableMessage(error, "Could not load resume templates."),
      );
    }
  }

  function selectTemplate(template: ResumeTemplate) {
    if (
      selectedTemplate?.kind === "custom" &&
      isDirty &&
      !window.confirm("Discard your unsaved template changes?")
    ) {
      return;
    }
    setSelectedId(template.id);
    setDraft(draftFromTemplate(template));
    setMessage("");
    setMessageKind(null);
  }

  async function saveTemplate() {
    if (!draft || !selectedTemplate || !draft.name.trim()) return;
    setMutation("saving");
    setMessage("");
    setMessageKind(null);
    try {
      const isCreate = selectedTemplate.kind === "bundled";
      const saved = await saveResumeTemplate(
        isCreate ? null : selectedTemplate.id,
        draft,
      );
      setTemplates((current) => upsertCustomTemplate(current, saved));
      setSelectedId(saved.id);
      setDraft(draftFromTemplate(saved));
      setMessage(
        isCreate
          ? "Personal template created."
          : `Template saved as version ${saved.version ?? "new"}.`,
      );
      setMessageKind("success");
    } catch (error) {
      setMessage(apiUnavailableMessage(error, "Could not save the template."));
      setMessageKind("error");
    } finally {
      setMutation(null);
    }
  }

  async function duplicateTemplate() {
    if (!selectedTemplate || selectedTemplate.kind !== "custom") return;
    setMutation("duplicating");
    setMessage("");
    setMessageKind(null);
    try {
      const duplicate = await duplicateResumeTemplate(selectedTemplate.id);
      setTemplates((current) => upsertCustomTemplate(current, duplicate));
      setSelectedId(duplicate.id);
      setDraft(draftFromTemplate(duplicate));
      setMessage("Template duplicated.");
      setMessageKind("success");
    } catch (error) {
      setMessage(
        apiUnavailableMessage(error, "Could not duplicate the template."),
      );
      setMessageKind("error");
    } finally {
      setMutation(null);
    }
  }

  async function deleteTemplate() {
    if (!selectedTemplate || selectedTemplate.kind !== "custom") return;
    if (
      !window.confirm(
        `Delete “${selectedTemplate.name}”? This cannot be undone.`,
      )
    ) {
      return;
    }
    setMutation("deleting");
    setMessage("");
    setMessageKind(null);
    try {
      await deleteResumeTemplate(selectedTemplate.id);
      const remaining = templates.filter(
        (template) => template.id !== selectedTemplate.id,
      );
      const next =
        remaining.find((template) => template.kind === "custom") ??
        remaining[0] ??
        null;
      setTemplates(remaining);
      setSelectedId(next?.id ?? null);
      setDraft(next ? draftFromTemplate(next) : null);
      setMessage("Template deleted.");
      setMessageKind("success");
    } catch (error) {
      setMessage(
        apiUnavailableMessage(error, "Could not delete the template."),
      );
      setMessageKind("error");
    } finally {
      setMutation(null);
    }
  }

  async function exportTemplate() {
    if (!selectedTemplate || selectedTemplate.kind !== "custom") return;
    if (
      isDirty &&
      !window.confirm(
        "Export the last saved version? Unsaved editor changes are not included.",
      )
    ) {
      return;
    }
    setMutation("exporting");
    setMessage("");
    setMessageKind(null);
    let objectUrl = "";
    try {
      const backup = await exportResumeTemplate(selectedTemplate.id);
      objectUrl = URL.createObjectURL(backup.blob);
      const download = document.createElement("a");
      download.href = objectUrl;
      download.download =
        backup.fileName ??
        `${safeBackupName(selectedTemplate.name)}.resume-template.local.json`;
      document.body.append(download);
      download.click();
      download.remove();
      setMessage(
        "Template backup downloaded. Keep it outside the repository, for example in Downloads or personal backup storage.",
      );
      setMessageKind("success");
    } catch (error) {
      setMessage(
        apiUnavailableMessage(error, "Could not export the template."),
      );
      setMessageKind("error");
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setMutation(null);
    }
  }

  async function importTemplate(file: File | undefined) {
    if (!file) return;
    if (
      selectedTemplate?.kind === "custom" &&
      isDirty &&
      !window.confirm("Discard unsaved changes and import a template backup?")
    ) {
      if (importInputRef.current) importInputRef.current.value = "";
      return;
    }
    setMutation("importing");
    setMessage("");
    setMessageKind(null);
    try {
      if (file.size > MAX_TEMPLATE_BACKUP_BYTES) {
        throw new Error("Template backup must be 32 KB or smaller.");
      }
      const raw = await file.text();
      const backup = JSON.parse(raw) as unknown;
      const imported = await importResumeTemplate(backup);
      setTemplates((current) => upsertCustomTemplate(current, imported));
      setSelectedId(imported.id);
      setDraft(draftFromTemplate(imported));
      setMessage(`Imported “${imported.name}” as a new personal template.`);
      setMessageKind("success");
    } catch (error) {
      const message =
        error instanceof SyntaxError
          ? "The selected file is not valid JSON."
          : apiUnavailableMessage(error, "Could not import the template.");
      setMessage(message);
      setMessageKind("error");
    } finally {
      if (importInputRef.current) importInputRef.current.value = "";
      setMutation(null);
    }
  }

  return (
    <section
      className="resume-template-manager overflow-hidden rounded-[10px] border border-border bg-[#ffffff] shadow-[0_24px_80px_rgba(0,0,0,0.24),inset_0_1px_0_rgba(255,255,255,0.025)]"
      aria-labelledby="resume-templates-title"
    >
      <header className="flex min-h-[84px] flex-col gap-4 border-b border-border bg-[radial-gradient(circle_at_6%_0%,rgba(255,90,0,0.07),transparent_18rem)] px-4 py-4 sm:flex-row sm:items-center sm:justify-between 2xl:px-[18px]">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-[#e95300] to-[#e95300] shadow-[0_8px_24px_rgba(255,90,0,0.24),inset_0_1px_0_rgba(255,255,255,0.28)]">
            <FileText className="h-5 w-5 text-foreground" />
          </span>
          <div>
            <h2
              id="resume-templates-title"
              className="text-[17px] font-bold leading-6 text-foreground"
            >
              Resume templates
            </h2>
            <p className="mt-0.5 text-xs leading-5 text-[#4a4a47]">
              Create owner-only designs from trusted templates and preview them
              before saving.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            aria-label="Import resume template backup"
            className="sr-only"
            onChange={(event) => void importTemplate(event.target.files?.[0])}
          />
          {status === "ready" ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={mutation !== null}
              onClick={() => importInputRef.current?.click()}
              className="h-10 rounded-md border border-border bg-[#fff8f1] px-4 text-[13px] font-bold text-[#1d1e1c] hover:bg-[#fff3e8]"
            >
              {mutation === "importing" ? (
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="h-3.5 w-3.5" />
              )}
              Import JSON
            </Button>
          ) : null}
          {status === "ready" && selectedTemplate && draft ? (
            <Button
              type="button"
              disabled={
                mutation !== null ||
                !draft.name.trim() ||
                !hasValidAccentColor ||
                (selectedTemplate.kind === "custom" && !isDirty)
              }
              onClick={() => void saveTemplate()}
              className="h-10 rounded-md bg-gradient-to-r from-[#e95300] to-[#e95300] px-4 text-[13px] font-bold shadow-[0_8px_24px_rgba(255,90,0,0.2)] hover:from-[#e95300] hover:to-[#e95300]"
            >
              {mutation === "saving" ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : selectedTemplate.kind === "bundled" ? (
                <Plus className="h-4 w-4" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {selectedTemplate.kind === "bundled" ? "Create template" : "Save"}
            </Button>
          ) : null}
          {status === "error" ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => void loadTemplates()}
              className="h-10 border border-border bg-[#fff8f1]"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </Button>
          ) : null}
        </div>
      </header>

      {status === "loading" ? (
        <div className="flex min-h-56 items-center justify-center gap-2 text-sm font-semibold text-muted">
          <LoaderCircle className="h-5 w-5 animate-spin text-accent" />
          Loading resume templates
        </div>
      ) : status === "error" ? (
        <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
          <LayoutTemplate className="h-8 w-8 text-muted" />
          <p className="mt-3 text-sm font-semibold text-foreground">
            Resume templates are unavailable
          </p>
          <p
            className="mt-1 max-w-md text-xs leading-5 text-accent"
            role="alert"
          >
            {message}
          </p>
        </div>
      ) : !selectedTemplate || !draft ? (
        <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
          <LayoutTemplate className="h-8 w-8 text-muted" />
          <p className="mt-3 text-sm font-semibold text-foreground">
            No template definitions found
          </p>
          <p className="mt-1 text-xs text-muted">
            Add a bundled template on the server to get started.
          </p>
        </div>
      ) : (
        <>
          <div className="grid min-w-0 lg:grid-cols-[250px_minmax(0,1fr)] xl:grid-cols-[270px_minmax(0,1fr)] 2xl:grid-cols-[290px_minmax(0,1fr)]">
            <aside className="border-b border-border bg-black/[0.08] lg:border-b-0 lg:border-r">
              <div className="job-scroll max-h-[780px] overflow-y-auto px-4 py-5 xl:max-h-[936px]">
                <TemplateGroup
                  title="My templates"
                  emptyText="No personal templates yet."
                  templates={customTemplates}
                  selectedId={selectedId}
                  onSelect={selectTemplate}
                />
                <TemplateGroup
                  title="Bundled foundations"
                  templates={bundledTemplates}
                  selectedId={selectedId}
                  onSelect={selectTemplate}
                  className="mt-5"
                />
              </div>
            </aside>

            <div className="grid min-w-0 xl:grid-cols-[minmax(410px,0.88fr)_minmax(500px,1.12fr)] 2xl:grid-cols-[minmax(460px,0.9fr)_minmax(560px,1.1fr)]">
              <ResumeTemplateEditor
                draft={draft}
                sourceKind={selectedTemplate.kind}
                layout={selectedTemplate.layout}
                isDirty={isDirty}
                isSaving={mutation === "saving"}
                isDuplicating={mutation === "duplicating"}
                isDeleting={mutation === "deleting"}
                isExporting={mutation === "exporting"}
                onChange={setDraft}
                onDuplicate={
                  selectedTemplate.kind === "custom"
                    ? () => void duplicateTemplate()
                    : undefined
                }
                onDelete={
                  selectedTemplate.kind === "custom"
                    ? () => void deleteTemplate()
                    : undefined
                }
                onExport={
                  selectedTemplate.kind === "custom"
                    ? () => void exportTemplate()
                    : undefined
                }
              />
              <ResumeTemplatePreview draft={draft} />
            </div>
          </div>
          {message ? (
            <div
              className={cn(
                "flex items-center gap-2 border-t border-border px-4 py-2.5 text-xs font-semibold",
                messageKind === "error"
                  ? "bg-accent/10 text-accent"
                  : "bg-accent/10 text-accent",
              )}
              role={messageKind === "error" ? "alert" : "status"}
            >
              {messageKind === "error" ? (
                <AlertTriangle className="h-3.5 w-3.5" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              {message}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function TemplateGroup({
  title,
  emptyText,
  templates,
  selectedId,
  onSelect,
  className,
}: {
  title: string;
  emptyText?: string;
  templates: ResumeTemplate[];
  selectedId: string | null;
  onSelect: (template: ResumeTemplate) => void;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#4a4a47]">
          {title}
        </h3>
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[#fff8f1] px-1 text-[10px] font-bold text-[#1d1e1c]">
          {templates.length}
        </span>
      </div>
      {templates.length ? (
        <div className="space-y-1">
          {templates.map((template) => {
            const selected = template.id === selectedId;
            return (
              <button
                key={template.id}
                type="button"
                onClick={() => onSelect(template)}
                aria-pressed={selected}
                className={cn(
                  "group relative flex min-h-[64px] w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  selected
                    ? "border-[#e95300]/70 bg-[linear-gradient(100deg,rgba(255,90,0,0.12),rgba(255,90,0,0.035))]"
                    : "border-transparent hover:border-[#c0bbb6] hover:bg-[#fff3e8]",
                )}
              >
                <span
                  className={cn(
                    "h-9 w-1 shrink-0 rounded-full",
                    selected && "shadow-[0_0_16px_rgba(255,90,0,0.3)]",
                  )}
                  style={{
                    backgroundColor: selected
                      ? "#e95300"
                      : template.designJson.accentColor,
                    opacity: selected ? 1 : 0.7,
                  }}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-bold text-foreground">
                    {template.name}
                  </span>
                  <span className="mt-1 flex items-center gap-1 text-[10px] font-medium text-[#615f5c]">
                    {template.kind === "bundled" ? (
                      <>
                        <FilePlus2 className="h-3 w-3" />
                        Customize
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3" />v{template.version ?? 1}
                      </>
                    )}
                    <span aria-hidden="true">·</span>
                    {template.columns === 2 ? "2 columns" : "1 column"}
                  </span>
                </span>
                <ChevronRight
                  className={cn(
                    "h-3.5 w-3.5 shrink-0 transition",
                    selected
                      ? "text-accent"
                      : "text-[#615f5c] group-hover:text-foreground",
                  )}
                />
              </button>
            );
          })}
        </div>
      ) : (
        <p className="rounded-md border border-border bg-[#fff8f1] px-3 py-3.5 text-xs leading-5 text-[#615f5c]">
          {emptyText}
        </p>
      )}
    </div>
  );
}

function draftFromTemplate(template: ResumeTemplate): ResumeTemplateDraft {
  return {
    name:
      template.kind === "bundled"
        ? `${template.name} — personal`
        : template.name,
    baseTemplateId: template.baseTemplateId,
    designJson: {
      ...template.designJson,
      pageMargins: { ...template.designJson.pageMargins },
      sidebarSections: [...template.designJson.sidebarSections],
    },
  };
}

function draftSignature(draft: ResumeTemplateDraft): string {
  return JSON.stringify(draft);
}

function upsertCustomTemplate(
  templates: ResumeTemplate[],
  next: ResumeTemplate,
): ResumeTemplate[] {
  const bundled = templates.filter((template) => template.kind === "bundled");
  const custom = templates
    .filter((template) => template.kind === "custom" && template.id !== next.id)
    .concat(next)
    .sort((left, right) =>
      String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? "")),
    );
  return [...bundled, ...custom];
}

function safeBackupName(name: string): string {
  return (
    name
      .trim()
      .replace(/[^A-Za-z0-9._-]+/g, "-")
      .replace(/^[-._]+|[-._]+$/g, "") || "resume-template"
  );
}
