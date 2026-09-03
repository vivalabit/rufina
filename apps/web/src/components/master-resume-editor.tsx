"use client";

import { useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  FileCheck2,
  FileText,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  confirmMasterResumeImport,
  importMasterResume,
  MASTER_RESUME_REVIEW_SECTIONS,
  uploadPrimaryResume,
  type MasterResume,
  type MasterResumeConfirmationResponse,
  type MasterResumeImportResponse,
  type MasterResumeReviewSectionName,
  type ProfileResume,
  type UploadedProfileResume,
} from "@/features/profile/api/master-resume-client";
import { cn } from "@/lib/utils";
import { apiUnavailableMessage } from "@/shared/api/client";

export { MASTER_RESUME_REVIEW_SECTIONS } from "@/features/profile/api/master-resume-client";
export type { MasterResume } from "@/features/profile/api/master-resume-client";

type ResumeSectionName = MasterResume["sectionOrder"][number];
type EvidenceBackedText = NonNullable<MasterResume["summary"]>;
type ResumeBullet = MasterResume["experiences"][number]["bullets"][number];
type MasterExperience = MasterResume["experiences"][number];
type MasterSkill = MasterResume["skills"][number];
type MasterEducation = MasterResume["education"][number];
type MasterProject = MasterResume["projects"][number];
type MasterCertification = MasterResume["certifications"][number];
type MasterLanguage = MasterResume["languages"][number];
type AdditionalSection = MasterResume["additionalSections"][number];

type RequestState = "idle" | "loading" | "error";

const sectionLabels: Record<MasterResumeReviewSectionName, string> = {
  contacts: "Contact details",
  summary: "Summary",
  skills: "Skills",
  experience: "Experience",
  education: "Education",
  projects: "Projects",
  certifications: "Certifications",
};

const sectionDescriptions: Record<MasterResumeReviewSectionName, string> = {
  contacts: "Check your name, contact details, headline, and source language.",
  summary: "Correct wording only when it remains supported by the imported resume.",
  skills: "Check every extracted skill and remove anything unsupported.",
  experience: "Verify employers, roles, dates, and every achievement bullet.",
  education: "Verify institutions, credentials, dates, and supporting details.",
  projects: "Review imported projects, roles, links, and project bullets.",
  certifications: "Verify certification names, issuers, and validity dates.",
};

export function MasterResumeEditor({
  profileResume,
  onProfileResumeUploaded,
}: {
  profileResume?: ProfileResume | null;
  onProfileResumeUploaded?: (file: UploadedProfileResume) => void;
}) {
  const uploadRef = useRef<HTMLInputElement>(null);
  const [importState, setImportState] = useState<RequestState>("idle");
  const [confirmState, setConfirmState] = useState<RequestState>("idle");
  const [message, setMessage] = useState("");
  const [importedFileName, setImportedFileName] = useState("");
  const [importResult, setImportResult] =
    useState<MasterResumeImportResponse | null>(null);
  const [draft, setDraft] = useState<MasterResume | null>(null);
  const [activeSection, setActiveSection] =
    useState<MasterResumeReviewSectionName>("contacts");
  const [reviewedSections, setReviewedSections] = useState<
    Set<MasterResumeReviewSectionName>
  >(new Set());
  const [dialogOpen, setDialogOpen] = useState(false);
  const [confirmation, setConfirmation] =
    useState<MasterResumeConfirmationResponse | null>(null);

  const allSectionsReviewed =
    reviewedSections.size === MASTER_RESUME_REVIEW_SECTIONS.length;
  const validationMessage = useMemo(
    () => (draft ? validateMasterResumeDraft(draft) : ""),
    [draft],
  );

  async function importResume(fileName: string, profileFileId: string) {
    setImportState("loading");
    setMessage("");
    setConfirmation(null);
    setImportedFileName(fileName);

    try {
      const payload = await importMasterResume(profileFileId);

      setImportResult(payload);
      setDraft(cloneResume(payload.masterResume));
      setReviewedSections(new Set());
      setActiveSection("contacts");
      setImportState("idle");
      setDialogOpen(true);
    } catch (error) {
      setImportState("error");
      setMessage(
        apiUnavailableMessage(
          error,
          "Master Resume import failed. Try again.",
        ),
      );
    }
  }

  async function importUploadedFile(file: File) {
    if (!isSupportedResumeFile(file)) {
      setImportState("error");
      setMessage("Choose a PDF or DOCX resume.");
      return;
    }
    try {
      const uploaded = await uploadPrimaryResume(file);
      onProfileResumeUploaded?.(uploaded);
      await importResume(uploaded.fileName, uploaded.id);
    } catch (error) {
      setImportState("error");
      setMessage(
        error instanceof Error
          ? error.message
          : "Could not read the selected resume.",
      );
    }
  }

  function updateDraft(
    section: MasterResumeReviewSectionName,
    updater: (current: MasterResume) => MasterResume,
  ) {
    setDraft((current) => {
      if (!current) return current;
      return normalizeSectionOrder(updater(current));
    });
    setReviewedSections((current) => {
      if (!current.has(section)) return current;
      const next = new Set(current);
      next.delete(section);
      return next;
    });
    setConfirmState("idle");
    setMessage("");
  }

  function markSectionReviewed(section: MasterResumeReviewSectionName) {
    setReviewedSections((current) => new Set(current).add(section));
    const index = MASTER_RESUME_REVIEW_SECTIONS.indexOf(section);
    const nextSection = MASTER_RESUME_REVIEW_SECTIONS[index + 1];
    if (nextSection) setActiveSection(nextSection);
  }

  async function confirmMasterResume() {
    if (!importResult || !draft || !allSectionsReviewed || validationMessage) {
      return;
    }
    setConfirmState("loading");
    setMessage("");
    try {
      const payload = await confirmMasterResumeImport(
        importResult.sourceFileId,
        draft,
      );
      setConfirmation(payload);
      setDraft(cloneResume(payload.masterResume));
      setConfirmState("idle");
      setDialogOpen(false);
      setMessage("Master Resume version 1 is confirmed and ready for tailoring.");
    } catch (error) {
      setConfirmState("error");
      setMessage(
        apiUnavailableMessage(
          error,
          "Master Resume confirmation failed. Try again.",
        ),
      );
    }
  }

  const sourceDetails = importResult
    ? [
        importResult.source.sourceFormat.toUpperCase(),
        importResult.source.pageCount
          ? `${importResult.source.pageCount} page${importResult.source.pageCount === 1 ? "" : "s"}`
          : "",
        `${importResult.source.fragments.length} source fragments`,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";

  return (
    <>
      <section className="panel overflow-hidden">
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center 2xl:p-5">
          <div className="flex min-w-0 items-start gap-3">
            <span
              className={cn(
                "grid h-11 w-11 shrink-0 place-items-center rounded-md border",
                confirmation
                  ? "border-success/30 bg-success/12 text-success"
                  : "border-accent/30 bg-accent/10 text-accent",
              )}
            >
              {confirmation ? (
                <FileCheck2 className="h-5 w-5" />
              ) : (
                <ShieldCheck className="h-5 w-5" />
              )}
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-bold text-foreground 2xl:text-lg">
                  Master Resume
                </h2>
                {confirmation ? (
                  <span className="rounded border border-success/30 bg-success/10 px-2 py-0.5 text-[11px] font-bold text-success">
                    Confirmed · v{confirmation.version}
                  </span>
                ) : draft ? (
                  <span className="rounded border border-[#fa5d00]/30 bg-[#fa5d00]/10 px-2 py-0.5 text-[11px] font-bold text-accent">
                    {reviewedSections.size}/
                    {MASTER_RESUME_REVIEW_SECTIONS.length} sections reviewed
                  </span>
                ) : null}
              </div>
              <p className="mt-1 max-w-[760px] text-xs leading-5 text-muted 2xl:text-[13px]">
                {confirmation
                  ? `${confirmation.masterResume.basics.fullName} is now the verified, vacancy-independent source for tailored resumes.`
                  : "Import once, review the structured facts, and confirm an immutable source of truth for future tailoring."}
              </p>
              {message ? (
                <p
                  role={importState === "error" ? "alert" : "status"}
                  className={cn(
                    "mt-2 text-xs font-semibold",
                    importState === "error" || confirmState === "error"
                      ? "text-[#fa5d00]"
                      : "text-success",
                  )}
                >
                  {message}
                </p>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap gap-2 lg:justify-end">
            {draft && !confirmation ? (
              <Button
                type="button"
                className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-4 text-xs font-bold text-foreground"
                onClick={() => setDialogOpen(true)}
              >
                <FileText className="h-4 w-4" />
                Continue review
              </Button>
            ) : null}
            {!confirmation && profileResume?.fileId ? (
              <Button
                type="button"
                variant="ghost"
                className="h-10 rounded-md border border-border bg-[#fff8f1] px-4 text-xs font-bold text-[#1d1e1c] hover:bg-[#fff3e8]"
                disabled={importState === "loading"}
                onClick={() =>
                  importResume(profileResume.fileName, profileResume.fileId)
                }
              >
                {importState === "loading" ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                {draft ? "Restart from profile resume" : "Import profile resume"}
              </Button>
            ) : null}
            {!confirmation ? (
              <Button
                type="button"
                variant="ghost"
                className="h-10 rounded-md border border-border bg-[#fff8f1] px-4 text-xs font-bold text-[#1d1e1c] hover:bg-[#fff3e8]"
                disabled={importState === "loading"}
                onClick={() => uploadRef.current?.click()}
              >
                <Upload className="h-4 w-4" />
                Choose PDF or DOCX
              </Button>
            ) : null}
            <input
              ref={uploadRef}
              aria-label="Choose Master Resume file"
              type="file"
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void importUploadedFile(file);
                event.currentTarget.value = "";
              }}
            />
          </div>
        </div>

        {!confirmation ? (
          <div className="grid border-t border-border bg-[#fff8f1] sm:grid-cols-3">
            <ProcessStep number="1" label="Import PDF or DOCX" />
            <ProcessStep number="2" label="Review all 7 sections" />
            <ProcessStep number="3" label="Confirm immutable v1" />
          </div>
        ) : null}
      </section>

      {dialogOpen && draft && importResult ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/78 p-2 backdrop-blur-sm sm:p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="master-resume-editor-title"
            className="panel flex h-[min(920px,calc(100vh-16px))] w-full max-w-[1180px] flex-col overflow-hidden border-border bg-white shadow-[6px_8px_36px_rgba(227,214,197,0.72)] sm:h-[min(900px,calc(100vh-32px))]"
          >
            <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-4 py-4 sm:px-5">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2
                    id="master-resume-editor-title"
                    className="text-xl font-bold text-foreground sm:text-2xl"
                  >
                    Review Master Resume
                  </h2>
                  <span className="rounded border border-accent/30 bg-accent/10 px-2 py-0.5 text-[11px] font-bold text-accent">
                    Draft
                  </span>
                </div>
                <p className="mt-1 truncate text-xs text-muted sm:text-[13px]">
                  {importedFileName} · {sourceDetails}
                </p>
              </div>
              <button
                type="button"
                aria-label="Close Master Resume editor"
                className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                disabled={confirmState === "loading"}
                onClick={() => setDialogOpen(false)}
              >
                <X className="h-5 w-5" />
              </button>
            </header>

            <div className="grid min-h-0 flex-1 md:grid-cols-[240px_minmax(0,1fr)]">
              <nav className="job-scroll flex gap-2 overflow-x-auto border-b border-border p-3 md:block md:overflow-y-auto md:border-b-0 md:border-r">
                {MASTER_RESUME_REVIEW_SECTIONS.map((section, index) => {
                  const reviewed = reviewedSections.has(section);
                  const itemCount =
                    importResult.reviewSections.find(
                      (item) => item.name === section,
                    )?.itemCount ?? 0;
                  return (
                    <button
                      key={section}
                      type="button"
                      aria-current={
                        activeSection === section ? "step" : undefined
                      }
                      className={cn(
                        "flex min-w-[180px] items-center gap-3 rounded-md border px-3 py-2.5 text-left transition md:mb-2 md:w-full md:min-w-0",
                        activeSection === section
                          ? "border-accent/45 bg-accent/10"
                          : "border-transparent hover:border-border hover:bg-[#fff3e8]",
                      )}
                      onClick={() => setActiveSection(section)}
                    >
                      <span
                        className={cn(
                          "grid h-7 w-7 shrink-0 place-items-center rounded-full border text-[11px] font-bold",
                          reviewed
                            ? "border-success/35 bg-success/12 text-success"
                            : "border-border bg-[#fff8f1] text-muted",
                        )}
                      >
                        {reviewed ? <Check className="h-4 w-4" /> : index + 1}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-xs font-bold text-foreground">
                          {sectionLabels[section]}
                        </span>
                        <span className="mt-0.5 block text-[11px] text-muted">
                          {itemCount} imported
                        </span>
                      </span>
                    </button>
                  );
                })}
              </nav>

              <main className="job-scroll min-h-0 overflow-y-auto p-4 sm:p-5">
                <div className="mx-auto max-w-[760px]">
                  <div className="mb-5">
                    <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-accent">
                      Section{" "}
                      {MASTER_RESUME_REVIEW_SECTIONS.indexOf(activeSection) + 1}{" "}
                      of {MASTER_RESUME_REVIEW_SECTIONS.length}
                    </p>
                    <h3 className="mt-1 text-lg font-bold text-foreground">
                      {sectionLabels[activeSection]}
                    </h3>
                    <p className="mt-1 text-xs leading-5 text-muted sm:text-[13px]">
                      {sectionDescriptions[activeSection]}
                    </p>
                  </div>

                  <SectionEditor
                    section={activeSection}
                    resume={draft}
                    onChange={(updater) =>
                      updateDraft(activeSection, updater)
                    }
                  />

                  <div className="mt-6 flex flex-col gap-3 border-t border-border pt-5 sm:flex-row sm:items-center sm:justify-between">
                    <p className="flex items-center gap-2 text-xs leading-5 text-muted">
                      <ShieldCheck className="h-4 w-4 shrink-0 text-accent" />
                      Source references are preserved automatically.
                    </p>
                    <Button
                      type="button"
                      variant="ghost"
                      className={cn(
                        "h-10 rounded-md border px-4 text-xs font-bold",
                        reviewedSections.has(activeSection)
                          ? "border-success/35 bg-success/10 text-success"
                          : "border-accent/40 bg-accent/10 text-foreground",
                      )}
                      onClick={() => markSectionReviewed(activeSection)}
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      {reviewedSections.has(activeSection)
                        ? "Reviewed"
                        : "Mark reviewed"}
                      {!reviewedSections.has(activeSection) ? (
                        <ChevronRight className="h-4 w-4" />
                      ) : null}
                    </Button>
                  </div>
                </div>
              </main>
            </div>

            <footer className="shrink-0 border-t border-border bg-[#ffffff] px-4 py-3 sm:px-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  {validationMessage ? (
                    <p role="alert" className="flex items-center gap-2 text-xs font-semibold text-[#fa5d00]">
                      <AlertTriangle className="h-4 w-4 shrink-0" />
                      {validationMessage}
                    </p>
                  ) : confirmState === "error" && message ? (
                    <p role="alert" className="flex items-center gap-2 text-xs font-semibold text-[#fa5d00]">
                      <AlertTriangle className="h-4 w-4 shrink-0" />
                      {message}
                    </p>
                  ) : (
                    <p className="flex items-center gap-2 text-xs text-muted">
                      <LockKeyhole className="h-4 w-4 shrink-0 text-accent" />
                      Confirmation creates immutable version 1 and cannot be edited.
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-10 rounded-md border border-border px-4 text-xs text-[#1d1e1c]"
                    disabled={confirmState === "loading"}
                    onClick={() => setDialogOpen(false)}
                  >
                    Close for now
                  </Button>
                  <Button
                    type="button"
                    className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-5 text-xs font-bold text-foreground disabled:opacity-45"
                    disabled={
                      !allSectionsReviewed ||
                      Boolean(validationMessage) ||
                      confirmState === "loading"
                    }
                    onClick={() => void confirmMasterResume()}
                  >
                    {confirmState === "loading" ? (
                      <LoaderCircle className="h-4 w-4 animate-spin" />
                    ) : (
                      <LockKeyhole className="h-4 w-4" />
                    )}
                    {confirmState === "loading"
                      ? "Confirming..."
                      : "Confirm Master Resume"}
                  </Button>
                </div>
              </div>
            </footer>
          </div>
        </div>
      ) : null}
    </>
  );
}

function SectionEditor({
  section,
  resume,
  onChange,
}: {
  section: MasterResumeReviewSectionName;
  resume: MasterResume;
  onChange: (updater: (current: MasterResume) => MasterResume) => void;
}) {
  if (section === "contacts") {
    const fields: Array<{
      key: keyof MasterResume["basics"];
      label: string;
      required?: boolean;
    }> = [
      { key: "fullName", label: "Full name", required: true },
      { key: "headline", label: "Headline" },
      { key: "email", label: "Email" },
      { key: "phone", label: "Phone" },
      { key: "location", label: "Location" },
      { key: "linkedin", label: "LinkedIn" },
      { key: "github", label: "GitHub" },
      { key: "portfolio", label: "Portfolio" },
    ];
    return (
      <div className="grid gap-4 sm:grid-cols-2">
        <EditorField
          label="Resume language"
          required
          value={resume.language}
          onChange={(value) =>
            onChange((current) => ({ ...current, language: value }))
          }
        />
        {fields.map((field) => (
          <EditorField
            key={field.key}
            label={field.label}
            required={field.required}
            value={resume.basics[field.key] ?? ""}
            onChange={(value) =>
              onChange((current) => ({
                ...current,
                basics: { ...current.basics, [field.key]: value },
              }))
            }
          />
        ))}
      </div>
    );
  }

  if (section === "summary") {
    if (!resume.summary) {
      return <EmptyImportedSection label="summary" />;
    }
    return (
      <EditorTextarea
        label="Professional summary"
        required
        rows={7}
        value={resume.summary.text}
        evidenceCount={resume.summary.evidenceIds.length}
        onChange={(value) =>
          onChange((current) => ({
            ...current,
            summary: current.summary
              ? { ...current.summary, text: value }
              : null,
          }))
        }
      />
    );
  }

  if (section === "skills") {
    if (resume.skills.length === 0) {
      return <EmptyImportedSection label="skills" />;
    }
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {resume.skills.map((skill, index) => (
          <EditorCard
            key={skill.id}
            title={`Skill ${index + 1}`}
            evidenceCount={skill.evidenceIds.length}
            onRemove={() =>
              onChange((current) => ({
                ...current,
                skills: current.skills.filter((item) => item.id !== skill.id),
              }))
            }
          >
            <EditorField
              label="Name"
              required
              value={skill.name}
              onChange={(value) =>
                onChange((current) => ({
                  ...current,
                  skills: replaceAt(current.skills, index, {
                    ...current.skills[index],
                    name: value,
                  }),
                }))
              }
            />
            <EditorField
              label="Category"
              value={skill.category ?? ""}
              onChange={(value) =>
                onChange((current) => ({
                  ...current,
                  skills: replaceAt(current.skills, index, {
                    ...current.skills[index],
                    category: value,
                  }),
                }))
              }
            />
          </EditorCard>
        ))}
      </div>
    );
  }

  if (section === "experience") {
    if (resume.experiences.length === 0) {
      return <EmptyImportedSection label="experience" />;
    }
    return (
      <div className="space-y-4">
        {resume.experiences.map((experience, experienceIndex) => (
          <EditorCard
            key={experience.id}
            title={`Experience ${experienceIndex + 1}`}
            onRemove={() =>
              onChange((current) => ({
                ...current,
                experiences: current.experiences.filter(
                  (item) => item.id !== experience.id,
                ),
              }))
            }
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  ["company", "Company", true],
                  ["title", "Title", true],
                  ["employmentType", "Employment type", false],
                  ["location", "Location", false],
                  ["startDate", "Start date", false],
                  ["endDate", "End date", false],
                ] as const
              ).map(([key, label, required]) => (
                <EditorField
                  key={key}
                  label={label}
                  required={required}
                  disabled={key === "endDate" && Boolean(experience.isCurrent)}
                  value={experience[key] ?? ""}
                  onChange={(value) =>
                    onChange((current) => ({
                      ...current,
                      experiences: replaceAt(
                        current.experiences,
                        experienceIndex,
                        {
                          ...current.experiences[experienceIndex],
                          [key]: value,
                        },
                      ),
                    }))
                  }
                />
              ))}
            </div>
            <label className="mt-3 flex items-center gap-2 text-xs font-semibold text-[#1d1e1c]">
              <input
                type="checkbox"
                checked={Boolean(experience.isCurrent)}
                onChange={(event) =>
                  onChange((current) => ({
                    ...current,
                    experiences: replaceAt(
                      current.experiences,
                      experienceIndex,
                      {
                        ...current.experiences[experienceIndex],
                        isCurrent: event.target.checked,
                        endDate: event.target.checked
                          ? ""
                          : current.experiences[experienceIndex].endDate,
                      },
                    ),
                  }))
                }
                className="h-4 w-4 accent-[#fa5d00]"
              />
              Current role
            </label>
            <div className="mt-4 space-y-3">
              {experience.bullets.map((bullet, bulletIndex) => (
                <EditorTextarea
                  key={bullet.id}
                  label={`Achievement ${bulletIndex + 1}`}
                  required
                  rows={3}
                  value={bullet.text}
                  evidenceCount={bullet.evidenceIds.length}
                  onChange={(value) =>
                    onChange((current) => {
                      const currentExperience =
                        current.experiences[experienceIndex];
                      return {
                        ...current,
                        experiences: replaceAt(
                          current.experiences,
                          experienceIndex,
                          {
                            ...currentExperience,
                            bullets: replaceAt(
                              currentExperience.bullets,
                              bulletIndex,
                              {
                                ...currentExperience.bullets[bulletIndex],
                                text: value,
                              },
                            ),
                          },
                        ),
                      };
                    })
                  }
                />
              ))}
            </div>
          </EditorCard>
        ))}
      </div>
    );
  }

  if (section === "education") {
    if (resume.education.length === 0) {
      return <EmptyImportedSection label="education" />;
    }
    return (
      <div className="space-y-4">
        {resume.education.map((education, educationIndex) => (
          <EditorCard
            key={education.id}
            title={`Education ${educationIndex + 1}`}
            onRemove={() =>
              onChange((current) => ({
                ...current,
                education: current.education.filter(
                  (item) => item.id !== education.id,
                ),
              }))
            }
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  ["institution", "Institution", true],
                  ["credential", "Credential", true],
                  ["fieldOfStudy", "Field of study", false],
                  ["location", "Location", false],
                  ["startDate", "Start date", false],
                  ["endDate", "End date", false],
                ] as const
              ).map(([key, label, required]) => (
                <EditorField
                  key={key}
                  label={label}
                  required={required}
                  value={education[key] ?? ""}
                  onChange={(value) =>
                    onChange((current) => ({
                      ...current,
                      education: replaceAt(
                        current.education,
                        educationIndex,
                        {
                          ...current.education[educationIndex],
                          [key]: value,
                        },
                      ),
                    }))
                  }
                />
              ))}
            </div>
            {education.details.length > 0 ? (
              <div className="mt-4 space-y-3">
                {education.details.map((detail, detailIndex) => (
                  <EditorTextarea
                    key={detail.id}
                    label={`Detail ${detailIndex + 1}`}
                    rows={3}
                    value={detail.text}
                    evidenceCount={detail.evidenceIds.length}
                    onChange={(value) =>
                      onChange((current) => {
                        const currentEducation =
                          current.education[educationIndex];
                        return {
                          ...current,
                          education: replaceAt(
                            current.education,
                            educationIndex,
                            {
                              ...currentEducation,
                              details: replaceAt(
                                currentEducation.details,
                                detailIndex,
                                {
                                  ...currentEducation.details[detailIndex],
                                  text: value,
                                },
                              ),
                            },
                          ),
                        };
                      })
                    }
                  />
                ))}
              </div>
            ) : null}
          </EditorCard>
        ))}
      </div>
    );
  }

  if (section === "projects") {
    if (resume.projects.length === 0) {
      return <EmptyImportedSection label="projects" />;
    }
    return (
      <div className="space-y-4">
        {resume.projects.map((project, projectIndex) => (
          <EditorCard
            key={project.id}
            title={`Project ${projectIndex + 1}`}
            onRemove={() =>
              onChange((current) => ({
                ...current,
                projects: current.projects.filter(
                  (item) => item.id !== project.id,
                ),
              }))
            }
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  ["name", "Project name", true],
                  ["role", "Role", false],
                  ["url", "URL", false],
                ] as const
              ).map(([key, label, required]) => (
                <EditorField
                  key={key}
                  label={label}
                  required={required}
                  value={project[key] ?? ""}
                  onChange={(value) =>
                    onChange((current) => ({
                      ...current,
                      projects: replaceAt(
                        current.projects,
                        projectIndex,
                        {
                          ...current.projects[projectIndex],
                          [key]: value,
                        },
                      ),
                    }))
                  }
                />
              ))}
            </div>
            <div className="mt-4 space-y-3">
              {project.bullets.map((bullet, bulletIndex) => (
                <EditorTextarea
                  key={bullet.id}
                  label={`Project result ${bulletIndex + 1}`}
                  required
                  rows={3}
                  value={bullet.text}
                  evidenceCount={bullet.evidenceIds.length}
                  onChange={(value) =>
                    onChange((current) => {
                      const currentProject = current.projects[projectIndex];
                      return {
                        ...current,
                        projects: replaceAt(
                          current.projects,
                          projectIndex,
                          {
                            ...currentProject,
                            bullets: replaceAt(
                              currentProject.bullets,
                              bulletIndex,
                              {
                                ...currentProject.bullets[bulletIndex],
                                text: value,
                              },
                            ),
                          },
                        ),
                      };
                    })
                  }
                />
              ))}
            </div>
          </EditorCard>
        ))}
      </div>
    );
  }

  if (resume.certifications.length === 0) {
    return <EmptyImportedSection label="certifications" />;
  }
  return (
    <div className="space-y-4">
      {resume.certifications.map((certification, certificationIndex) => (
        <EditorCard
          key={certification.id}
          title={`Certification ${certificationIndex + 1}`}
          evidenceCount={certification.evidenceIds.length}
          onRemove={() =>
            onChange((current) => ({
              ...current,
              certifications: current.certifications.filter(
                (item) => item.id !== certification.id,
              ),
            }))
          }
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                ["name", "Certification", true],
                ["issuer", "Issuer", true],
                ["issuedOn", "Issued on", false],
                ["expiresOn", "Expires on", false],
              ] as const
            ).map(([key, label, required]) => (
              <EditorField
                key={key}
                label={label}
                required={required}
                value={certification[key] ?? ""}
                onChange={(value) =>
                  onChange((current) => ({
                    ...current,
                    certifications: replaceAt(
                      current.certifications,
                      certificationIndex,
                      {
                        ...current.certifications[certificationIndex],
                        [key]: value,
                      },
                    ),
                  }))
                }
              />
            ))}
          </div>
        </EditorCard>
      ))}
    </div>
  );
}

function ProcessStep({ number, label }: { number: string; label: string }) {
  return (
    <div className="flex items-center gap-2 border-border px-4 py-2.5 text-xs font-semibold text-muted sm:border-r sm:last:border-r-0">
      <span className="grid h-5 w-5 place-items-center rounded-full border border-border bg-[#fff8f1] text-[10px] font-bold text-[#1d1e1c]">
        {number}
      </span>
      {label}
    </div>
  );
}

function EmptyImportedSection({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-dashed border-border bg-[#fff8f1] p-5 text-center">
      <FileText className="mx-auto h-6 w-6 text-muted" />
      <p className="mt-2 text-sm font-bold text-foreground">
        No {label} imported
      </p>
      <p className="mt-1 text-xs leading-5 text-muted">
        This is valid when the source resume does not contain supported content
        for this section.
      </p>
    </div>
  );
}

function EditorCard({
  title,
  evidenceCount,
  onRemove,
  children,
}: {
  title: string;
  evidenceCount?: number;
  onRemove: () => void;
  children: ReactNode;
}) {
  return (
    <article className="rounded-md border border-border bg-[#fff8f1] p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-sm font-bold text-foreground">{title}</h4>
          {evidenceCount ? <EvidenceBadge count={evidenceCount} /> : null}
        </div>
        <button
          type="button"
          aria-label={`Remove ${title}`}
          className="inline-flex items-center gap-1 text-[11px] font-semibold text-muted transition hover:text-[#fa5d00]"
          onClick={onRemove}
        >
          <Trash2 className="h-3.5 w-3.5" />
          Remove
        </button>
      </div>
      {children}
    </article>
  );
}

function EditorField({
  label,
  value,
  onChange,
  required = false,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  disabled?: boolean;
}) {
  return (
    <label className="grid gap-1.5">
      <span className="text-xs font-bold text-[#1d1e1c]">
        {label}
        {required ? <span className="ml-1 text-accent">*</span> : null}
      </span>
      <input
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 min-w-0 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-medium text-foreground outline-none placeholder:text-muted/60 focus:border-accent/65 disabled:cursor-not-allowed disabled:opacity-45"
      />
    </label>
  );
}

function EditorTextarea({
  label,
  value,
  onChange,
  evidenceCount,
  required = false,
  rows = 4,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  evidenceCount?: number;
  required?: boolean;
  rows?: number;
}) {
  return (
    <label className="grid gap-1.5">
      <span className="flex flex-wrap items-center gap-2 text-xs font-bold text-[#1d1e1c]">
        <span>
          {label}
          {required ? <span className="ml-1 text-accent">*</span> : null}
        </span>
        {evidenceCount ? <EvidenceBadge count={evidenceCount} /> : null}
      </span>
      <textarea
        aria-label={label}
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-w-0 resize-y rounded-md border border-border bg-[#ffffff] px-3 py-2.5 text-sm font-medium leading-6 text-foreground outline-none placeholder:text-muted/60 focus:border-accent/65"
      />
    </label>
  );
}

function EvidenceBadge({ count }: { count: number }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-[#fa5d00]/25 bg-[#fa5d00]/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
      <ShieldCheck className="h-3 w-3" />
      {count} source {count === 1 ? "reference" : "references"}
    </span>
  );
}

function cloneResume(resume: MasterResume): MasterResume {
  return structuredClone(resume);
}

function replaceAt<T>(items: T[], index: number, value: T): T[] {
  return items.map((item, currentIndex) =>
    currentIndex === index ? value : item,
  );
}

function normalizeSectionOrder(resume: MasterResume): MasterResume {
  const present = new Set<ResumeSectionName>();
  if (resume.summary) present.add("summary");
  if (resume.experiences.length) present.add("experience");
  if (resume.skills.length) present.add("skills");
  if (resume.education.length) present.add("education");
  if (resume.projects.length) present.add("projects");
  if (resume.certifications.length) present.add("certifications");
  if (resume.languages.length) present.add("languages");
  if (resume.additionalSections.length) present.add("additional");

  const sectionOrder = resume.sectionOrder.filter((section) =>
    present.has(section),
  );
  for (const section of present) {
    if (!sectionOrder.includes(section)) sectionOrder.push(section);
  }
  return { ...resume, sectionOrder };
}

function validateMasterResumeDraft(resume: MasterResume): string {
  if (!resume.basics.fullName.trim()) return "Full name is required.";
  if (!resume.language.trim()) return "Resume language is required.";
  if (resume.summary && !resume.summary.text.trim()) {
    return "Summary cannot be empty.";
  }
  for (const skill of resume.skills) {
    if (!skill.name.trim()) return "Every skill needs a name.";
  }
  for (const experience of resume.experiences) {
    if (!experience.company.trim() || !experience.title.trim()) {
      return "Every experience needs a company and title.";
    }
    if (experience.bullets.some((bullet) => !bullet.text.trim())) {
      return "Experience achievements cannot be empty.";
    }
  }
  for (const education of resume.education) {
    if (!education.institution.trim() || !education.credential.trim()) {
      return "Every education entry needs an institution and credential.";
    }
    if (education.details.some((detail) => !detail.text.trim())) {
      return "Education details cannot be empty.";
    }
  }
  for (const project of resume.projects) {
    if (!project.name.trim()) return "Every project needs a name.";
    if (project.bullets.some((bullet) => !bullet.text.trim())) {
      return "Project results cannot be empty.";
    }
  }
  for (const certification of resume.certifications) {
    if (!certification.name.trim() || !certification.issuer.trim()) {
      return "Every certification needs a name and issuer.";
    }
  }
  return "";
}

function isSupportedResumeFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return (
    name.endsWith(".pdf") ||
    name.endsWith(".docx") ||
    file.type === "application/pdf" ||
    file.type ===
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  );
}
