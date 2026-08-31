"use client";

import { Save, Upload, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { documentCategories } from "@/features/profile/model/defaults";
import type {
  DocumentEntry,
  EducationEntry,
  ExperienceEntry,
} from "@/shared/types/profile";
import { cn } from "@/lib/utils";

export function ExperienceEditorDialog({
  experience,
  isEditMode,
  status,
  message,
  onChange,
  onClose,
  onSave,
}: {
  experience: ExperienceEntry;
  isEditMode: boolean;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onChange: <Field extends keyof ExperienceEntry>(
    field: Field,
    value: ExperienceEntry[Field],
  ) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[760px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
              {isEditMode ? "Edit Experience" : "Add Experience"}
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              {isEditMode
                ? "Update this role, internship, freelance project, or relevant IT project."
                : "Add one role, internship, freelance project, or relevant IT project."}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close experience editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Role title
              </span>
              <input
                value={experience.title}
                onChange={(event) => onChange("title", event.target.value)}
                placeholder="e.g. Junior Python Developer"
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Company / project
              </span>
              <input
                value={experience.company}
                onChange={(event) => onChange("company", event.target.value)}
                placeholder="Company name or project name"
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Employment type
              </span>
              <select
                value={experience.employment_type}
                onChange={(event) =>
                  onChange("employment_type", event.target.value)
                }
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
              >
                <option>Full-time</option>
                <option>Part-time</option>
                <option>Internship</option>
                <option>Freelance</option>
                <option>Contract</option>
                <option>Project</option>
              </select>
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">Location</span>
              <input
                value={experience.location}
                onChange={(event) => onChange("location", event.target.value)}
                placeholder="Remote, Zurich, Switzerland..."
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Start date
              </span>
              <input
                type="month"
                value={experience.start_date}
                onChange={(event) => onChange("start_date", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">End date</span>
              <input
                type="month"
                value={experience.end_date}
                disabled={experience.is_current}
                onChange={(event) => onChange("end_date", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none disabled:opacity-45 focus:border-accent/70"
              />
            </label>

            <label className="flex items-start gap-3 rounded-md border border-border bg-[#fff8f1] p-3 md:col-span-2">
              <input
                type="checkbox"
                checked={experience.is_current}
                onChange={(event) => {
                  onChange("is_current", event.target.checked);
                  if (event.target.checked) {
                    onChange("end_date", "");
                  }
                }}
                className="mt-1 h-4 w-4 accent-accent"
              />
              <span>
                <span className="block text-sm font-bold text-foreground">
                  I currently work here
                </span>
                <span className="mt-1 block text-xs text-muted">
                  End date will be shown as Present.
                </span>
              </span>
            </label>

            <label className="grid gap-2 md:col-span-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Description
              </span>
              <textarea
                value={experience.description}
                onChange={(event) =>
                  onChange("description", event.target.value)
                }
                placeholder="What did you build, support, automate, or improve?"
                rows={5}
                className="min-h-[128px] resize-none rounded-md border border-border bg-[#ffffff] px-3 py-2.5 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p
            className={cn(
              "text-sm font-semibold",
              status === "error" ? "text-[#fa5d00]" : "text-muted",
            )}
          >
            {message || "Role title and company are required"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#e95300] hover:to-[#e95300]"
              disabled={status === "loading"}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {status === "loading" ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function EducationEditorDialog({
  education,
  isEditMode,
  status,
  message,
  onChange,
  onClose,
  onSave,
}: {
  education: EducationEntry;
  isEditMode: boolean;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onChange: <Field extends keyof EducationEntry>(
    field: Field,
    value: EducationEntry[Field],
  ) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[760px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
              {isEditMode ? "Edit Education" : "Add Education"}
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              {isEditMode
                ? "Update this degree, course, certification, or training."
                : "Add one degree, course, certification, or training."}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close education editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Institution
              </span>
              <input
                value={education.institution}
                onChange={(event) =>
                  onChange("institution", event.target.value)
                }
                placeholder="University, school, provider..."
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Credential
              </span>
              <input
                value={education.credential}
                onChange={(event) => onChange("credential", event.target.value)}
                placeholder="Bachelor, certificate, course name..."
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Field of study
              </span>
              <input
                value={education.field_of_study}
                onChange={(event) =>
                  onChange("field_of_study", event.target.value)
                }
                placeholder="Computer Science, Data Analytics..."
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">Location</span>
              <input
                value={education.location}
                onChange={(event) => onChange("location", event.target.value)}
                placeholder="Remote, Zurich, Switzerland..."
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Start date
              </span>
              <input
                type="month"
                value={education.start_date}
                onChange={(event) => onChange("start_date", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">End date</span>
              <input
                type="month"
                value={education.end_date}
                disabled={education.is_current}
                onChange={(event) => onChange("end_date", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none disabled:opacity-45 focus:border-accent/70"
              />
            </label>

            <label className="flex items-start gap-3 rounded-md border border-border bg-[#fff8f1] p-3 md:col-span-2">
              <input
                type="checkbox"
                checked={education.is_current}
                onChange={(event) => {
                  onChange("is_current", event.target.checked);
                  if (event.target.checked) {
                    onChange("end_date", "");
                  }
                }}
                className="mt-1 h-4 w-4 accent-accent"
              />
              <span>
                <span className="block text-sm font-bold text-foreground">
                  I currently study here
                </span>
                <span className="mt-1 block text-xs text-muted">
                  End date will be shown as Present.
                </span>
              </span>
            </label>

            <label className="grid gap-2 md:col-span-2">
              <span className="text-xs font-bold text-[#1d1e1c]">Details</span>
              <textarea
                value={education.description}
                onChange={(event) =>
                  onChange("description", event.target.value)
                }
                placeholder="Relevant coursework, honors, thesis, certification ID, or training details..."
                rows={5}
                className="min-h-[128px] resize-none rounded-md border border-border bg-[#ffffff] px-3 py-2.5 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p
            className={cn(
              "text-sm font-semibold",
              status === "error" ? "text-[#fa5d00]" : "text-muted",
            )}
          >
            {message || "Institution and credential are required"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#e95300] hover:to-[#e95300]"
              disabled={status === "loading"}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {status === "loading" ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function DocumentEditorDialog({
  document,
  isEditMode,
  status,
  message,
  onChange,
  onAttachFile,
  onClose,
  onSave,
}: {
  document: DocumentEntry;
  isEditMode: boolean;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onChange: <Field extends keyof DocumentEntry>(
    field: Field,
    value: DocumentEntry[Field],
  ) => void;
  onAttachFile: (file: File) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const isGeneratedDocumentSource = document.category === "CV / Resume";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[720px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
              {isEditMode ? "Edit Document" : "Add Document"}
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Label a reusable personal file and attach it to your profile
              library.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close document editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Document title
              </span>
              <input
                value={document.title}
                onChange={(event) => onChange("title", event.target.value)}
                placeholder="Main CV, Swiss work permit, diploma..."
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#1d1e1c]">Type</span>
              <select
                value={document.category}
                onChange={(event) => onChange("category", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
              >
                {documentCategories.map((category) => (
                  <option key={category}>{category}</option>
                ))}
              </select>
            </label>

            {isGeneratedDocumentSource ? (
              <label className="grid gap-2 md:col-span-2">
                <span className="text-xs font-bold text-[#1d1e1c]">
                  Document language
                </span>
                <select
                  value={document.language}
                  onChange={(event) => onChange("language", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none focus:border-accent/70"
                >
                  <option value="">Select language</option>
                  <option value="English">English</option>
                  <option value="German">German</option>
                </select>
                <span className="text-[11px] leading-4 text-muted">
                  Add separate English and German DOCX versions so Rufina can
                  select the right one for each vacancy.
                </span>
              </label>
            ) : null}

            <label className="grid gap-2 md:col-span-2">
              <span className="text-xs font-bold text-[#1d1e1c]">
                Issued by / source
              </span>
              <input
                value={document.issuer}
                onChange={(event) => onChange("issuer", event.target.value)}
                placeholder="University, certification provider, employer, immigration office..."
                className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <div className="rounded-md border border-border bg-[#fff8f1] p-3 md:col-span-2">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="text-sm font-bold text-foreground">
                    Attached file
                  </p>
                  <p className="mt-1 truncate text-xs text-muted">
                    {document.file_name
                      ? `${document.file_name}${document.file_size ? ` • ${document.file_size}` : ""}`
                      : isGeneratedDocumentSource
                        ? "DOCX under 5MB — its design will be preserved"
                        : "PDF, DOC, DOCX, PNG, JPG, or WebP under 5MB"}
                  </p>
                </div>
                <label className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-md border border-border bg-[#fff8f1] px-3 text-xs font-semibold text-[#1d1e1c] transition hover:bg-[#fff3e8]">
                  <Upload className="h-4 w-4" />
                  {document.file_name ? "Replace file" : "Attach file"}
                  <input
                    type="file"
                    accept={
                      isGeneratedDocumentSource
                        ? ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        : ".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg,image/webp"
                    }
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) {
                        onAttachFile(file);
                      }
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </div>
            </div>

            <label className="grid gap-2 md:col-span-2">
              <span className="text-xs font-bold text-[#1d1e1c]">Notes</span>
              <textarea
                value={document.notes}
                onChange={(event) => onChange("notes", event.target.value)}
                placeholder="When to use it, expiration date, original language, or anything important..."
                rows={4}
                className="min-h-[112px] resize-none rounded-md border border-border bg-[#ffffff] px-3 py-2.5 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p
            className={cn(
              "text-sm font-semibold",
              status === "error" ? "text-[#fa5d00]" : "text-muted",
            )}
          >
            {message || "Title and file are required"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#e95300] hover:to-[#e95300]"
              disabled={status === "loading"}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {status === "loading" ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
