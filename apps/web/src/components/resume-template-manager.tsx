"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Copy,
  FilePlus2,
  LayoutTemplate,
  LoaderCircle,
  Palette,
  RefreshCw,
  Upload,
} from "lucide-react";

import {
  ResumeTemplateEditor,
} from "@/components/resume-template-editor";
import { ResumeTemplatePreview } from "@/components/resume-template-preview";
import { Button } from "@/components/ui/button";
import { apiUnavailableMessage, fetchWithTimeout } from "@/lib/api-client";
import type {
  ResumeTemplate,
  ResumeTemplateDraft,
} from "@/lib/resume-templates";
import { cn } from "@/lib/utils";

type ManagerStatus = "loading" | "ready" | "error";
type MutationKind =
  | "saving"
  | "duplicating"
  | "deleting"
  | "exporting"
  | "importing"
  | null;
type MessageKind = "success" | "error" | null;
const MAX_TEMPLATE_BACKUP_BYTES = 32_000;

export function ResumeTemplateManager({
  apiBaseUrl,
}: {
  apiBaseUrl: string;
}) {
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

  useEffect(() => {
    const controller = new AbortController();
    void loadTemplates(controller.signal);
    return () => controller.abort();
    // Loading is intentionally scoped to the API base URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBaseUrl]);

  async function loadTemplates(signal?: AbortSignal) {
    setStatus("loading");
    setMessage("");
    setMessageKind(null);
    try {
      const response = await fetchWithTimeout(
        `${apiBaseUrl}/resume-templates`,
        { cache: "no-store", signal },
      );
      if (!response.ok) throw new Error(await readApiError(response));
      const nextTemplates = (await response.json()) as ResumeTemplate[];
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
      const response = await fetchWithTimeout(
        isCreate
          ? `${apiBaseUrl}/resume-templates`
          : `${apiBaseUrl}/resume-templates/${encodeURIComponent(selectedTemplate.id)}`,
        {
          method: isCreate ? "POST" : "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: draft.name.trim(),
            baseTemplateId: draft.baseTemplateId,
            designJson: draft.designJson,
          }),
        },
      );
      if (!response.ok) throw new Error(await readApiError(response));
      const saved = (await response.json()) as ResumeTemplate;
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
      const response = await fetchWithTimeout(
        `${apiBaseUrl}/resume-templates/${encodeURIComponent(selectedTemplate.id)}/duplicate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        },
      );
      if (!response.ok) throw new Error(await readApiError(response));
      const duplicate = (await response.json()) as ResumeTemplate;
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
      const response = await fetchWithTimeout(
        `${apiBaseUrl}/resume-templates/${encodeURIComponent(selectedTemplate.id)}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error(await readApiError(response));
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
      const response = await fetchWithTimeout(
        `${apiBaseUrl}/resume-templates/${encodeURIComponent(selectedTemplate.id)}/export`,
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error(await readApiError(response));
      const backup = await response.blob();
      objectUrl = URL.createObjectURL(backup);
      const download = document.createElement("a");
      download.href = objectUrl;
      download.download =
        responseFileName(response) ??
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
      const response = await fetchWithTimeout(
        `${apiBaseUrl}/resume-templates/import`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(backup),
        },
      );
      if (!response.ok) throw new Error(await readApiError(response));
      const imported = (await response.json()) as ResumeTemplate;
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
    <section className="panel overflow-hidden" aria-labelledby="resume-templates-title">
      <header className="flex flex-col gap-3 border-b border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between 2xl:px-5">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent/20 bg-accent/[0.08]">
            <Palette className="h-4 w-4 text-accent" />
          </span>
          <div>
            <h2
              id="resume-templates-title"
              className="text-base font-bold text-white"
            >
              Resume templates
            </h2>
            <p className="mt-0.5 text-xs leading-5 text-muted">
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
            onChange={(event) =>
              void importTemplate(event.target.files?.[0])
            }
          />
          {status === "ready" ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={mutation !== null}
              onClick={() => importInputRef.current?.click()}
              className="border border-border bg-white/[0.025]"
            >
              {mutation === "importing" ? (
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="h-3.5 w-3.5" />
              )}
              Import JSON
            </Button>
          ) : null}
          {status === "error" ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => void loadTemplates()}
              className="border border-border bg-white/[0.025]"
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
          <p className="mt-3 text-sm font-semibold text-white">
            Resume templates are unavailable
          </p>
          <p className="mt-1 max-w-md text-xs leading-5 text-red-300" role="alert">
            {message}
          </p>
        </div>
      ) : !selectedTemplate || !draft ? (
        <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
          <LayoutTemplate className="h-8 w-8 text-muted" />
          <p className="mt-3 text-sm font-semibold text-white">
            No template definitions found
          </p>
          <p className="mt-1 text-xs text-muted">
            Add a bundled template on the server to get started.
          </p>
        </div>
      ) : (
        <>
          <div className="grid min-w-0 lg:grid-cols-[250px_minmax(0,1fr)] 2xl:grid-cols-[270px_minmax(0,1fr)]">
            <aside className="border-b border-border bg-black/10 lg:border-b-0 lg:border-r">
              <div className="job-scroll max-h-[720px] overflow-y-auto p-3">
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

            <div className="grid min-w-0 xl:grid-cols-[minmax(360px,0.9fr)_minmax(420px,1.1fr)]">
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
                onSave={() => void saveTemplate()}
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
              <ResumeTemplatePreview apiBaseUrl={apiBaseUrl} draft={draft} />
            </div>
          </div>
          {message ? (
            <div
              className={cn(
                "flex items-center gap-2 border-t border-border px-4 py-2.5 text-xs font-semibold",
                messageKind === "error"
                  ? "bg-red-400/[0.06] text-red-300"
                  : "bg-emerald-400/[0.05] text-emerald-300",
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
      <div className="mb-2 flex items-center justify-between px-1">
        <h3 className="text-[10px] font-bold uppercase tracking-[0.15em] text-muted">
          {title}
        </h3>
        <span className="text-[10px] font-semibold text-muted">
          {templates.length}
        </span>
      </div>
      {templates.length ? (
        <div className="space-y-1.5">
          {templates.map((template) => {
            const selected = template.id === selectedId;
            return (
              <button
                key={template.id}
                type="button"
                onClick={() => onSelect(template)}
                aria-pressed={selected}
                className={cn(
                  "group flex w-full items-center gap-2.5 rounded-md border px-2.5 py-2.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  selected
                    ? "border-accent/45 bg-accent/[0.09]"
                    : "border-transparent hover:border-border hover:bg-white/[0.035]",
                )}
              >
                <span
                  className="h-8 w-1 shrink-0 rounded-full"
                  style={{ backgroundColor: template.designJson.accentColor }}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-bold text-white">
                    {template.name}
                  </span>
                  <span className="mt-0.5 flex items-center gap-1 text-[10px] font-medium text-muted">
                    {template.kind === "bundled" ? (
                      <>
                        <FilePlus2 className="h-3 w-3" />
                        Customize
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3" />
                        v{template.version ?? 1}
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
                      : "text-muted/60 group-hover:text-muted",
                  )}
                />
              </button>
            );
          })}
        </div>
      ) : (
        <p className="rounded-md border border-dashed border-border px-3 py-3 text-xs leading-5 text-muted">
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
    .filter(
      (template) =>
        template.kind === "custom" && template.id !== next.id,
    )
    .concat(next)
    .sort((left, right) =>
      String(right.updatedAt ?? "").localeCompare(
        String(left.updatedAt ?? ""),
      ),
    );
  return [...bundled, ...custom];
}

async function readApiError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as {
      detail?: unknown;
    };
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // Fall through to a status-based message.
  }
  return `Resume template request failed (${response.status}).`;
}

function responseFileName(response: Response): string | null {
  const disposition = response.headers.get("Content-Disposition");
  const match = disposition?.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? null;
}

function safeBackupName(name: string): string {
  return (
    name
      .trim()
      .replace(/[^A-Za-z0-9._-]+/g, "-")
      .replace(/^[-._]+|[-._]+$/g, "") || "resume-template"
  );
}
