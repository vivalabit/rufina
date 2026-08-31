"use client";

import {
  Ban,
  BriefcaseBusiness,
  Check,
  CircleDot,
  Download,
  Edit3,
  ExternalLink,
  FileText,
  Github,
  Globe,
  GraduationCap,
  Linkedin,
  MapPin,
  Plus,
  Sparkles,
  Star,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { MasterResumeEditor } from "@/components/master-resume-editor";
import { ResumeTemplateManager } from "@/components/resume-template-manager";
import { assistantPrompts } from "@/features/app-shell/model/assistant-prompts";
import { defaultCandidateProfile } from "@/features/profile/model/defaults";
import {
  parseDocumentEntries as parseDocumentEntriesModel,
  parseEducationEntries as parseEducationEntriesModel,
  parseExperienceEntries as parseExperienceEntriesModel,
  parseProfileLines,
} from "@/features/profile/model/entries";
import { hasProfileValue } from "@/features/profile/model/normalizers";
import {
  formatPreferenceSummary,
  parseJobPreferences,
} from "@/features/profile/model/preferences";
import {
  getAiMatchProfile as getAiMatchProfileModel,
  getProfileCompletion as getProfileCompletionModel,
  getProfileCompletionItems as getProfileCompletionItemsModel,
} from "@/features/profile/model/selectors";
import {
  displayProfileValue,
  formatProfileDate,
} from "@/features/profile/formatting";
import { apiBaseUrl } from "@/shared/api/config";
import { normalizeExternalUrl } from "@/shared/formatting/urls";
import type {
  CandidateProfile,
  DocumentEntry,
  EducationEntry,
  ExperienceEntry,
} from "@/shared/types/profile";
import { createClientId } from "@/lib/client-id";
import { cn } from "@/lib/utils";

function parseExperienceEntries(value: string) {
  return parseExperienceEntriesModel(value, createClientId);
}

function parseEducationEntries(value: string) {
  return parseEducationEntriesModel(value, createClientId);
}

function parseDocumentEntries(value: string) {
  return parseDocumentEntriesModel(value, createClientId);
}

function getAiMatchProfile(profile: CandidateProfile) {
  return getAiMatchProfileModel(profile, createClientId);
}

function getProfileCompletion(profile: CandidateProfile) {
  return getProfileCompletionModel(profile, createClientId);
}

function getProfileCompletionItems(profile: CandidateProfile) {
  return getProfileCompletionItemsModel(profile, createClientId);
}

function getProfileLinks(profile: CandidateProfile) {
  return [
    { label: "LinkedIn", value: profile.linkedin, icon: Linkedin },
    { label: "GitHub", value: profile.github, icon: Github },
    { label: "Portfolio", value: profile.portfolio, icon: FileText },
    { label: "Personal Site", value: profile.personal_site, icon: Globe },
  ].map((link) => ({ ...link, href: normalizeExternalUrl(link.value) }));
}

export function ProfileView({
  profile,
  onProfileResumeUploaded,
  onOpenAssistant,
  onEditProfile,
  onAddExperience,
  onEditExperience,
  onDeleteExperience,
  onImportExperienceFromCv,
  isExperienceImporting,
  experienceImportMessage,
  onAddEducation,
  onEditEducation,
  onDeleteEducation,
  onImportEducationFromCv,
  isEducationImporting,
  educationImportMessage,
  onAddDocument,
  onEditDocument,
  onDeleteDocument,
  onEditPreferences,
  onEditSkills,
  onEditDealbreakers,
  onEditAdditionalNotes,
  onImportSkillsFromCv,
  isSkillsImporting,
  skillsImportMessage,
}: {
  profile: CandidateProfile;
  onProfileResumeUploaded: (file: {
    id: string;
    fileName: string;
    sizeBytes: number;
    updatedAt: string;
    downloadUrl: string;
  }) => void;
  onOpenAssistant: (prompt: string) => void;
  onEditProfile: () => void;
  onAddExperience: () => void;
  onEditExperience: (experience: ExperienceEntry) => void;
  onDeleteExperience: (experienceId: string) => void;
  onImportExperienceFromCv: () => void;
  isExperienceImporting: boolean;
  experienceImportMessage: string;
  onAddEducation: () => void;
  onEditEducation: (education: EducationEntry) => void;
  onDeleteEducation: (educationId: string) => void;
  onImportEducationFromCv: () => void;
  isEducationImporting: boolean;
  educationImportMessage: string;
  onAddDocument: () => void;
  onEditDocument: (document: DocumentEntry) => void;
  onDeleteDocument: (documentId: string) => void;
  onEditPreferences: () => void;
  onEditSkills: () => void;
  onEditDealbreakers: () => void;
  onEditAdditionalNotes: () => void;
  onImportSkillsFromCv: () => void;
  isSkillsImporting: boolean;
  skillsImportMessage: string;
}) {
  return (
    <section className="job-scroll flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-4 flex shrink-0 flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="page-title text-[24px] leading-tight text-foreground sm:text-[27px] 2xl:text-[31px]">
            My Profile
          </h1>
          <p className="mt-1 text-[13px] text-muted 2xl:mt-1.5 2xl:text-base">
            Your professional profile and job preferences
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenAssistant(assistantPrompts.improveProfile)}
            className="h-10 rounded-md border border-accent/40 bg-accent/[0.055] px-3 text-xs font-bold text-foreground hover:bg-accent/[0.11] 2xl:h-11 2xl:px-4 2xl:text-sm"
          >
            <Sparkles className="h-4 w-4 text-accent" />
            Improve profile
          </Button>
        </div>
      </header>

      <ProfileHero profile={profile} onEditProfile={onEditProfile} />

      <div className="mt-4 grid shrink-0 content-start gap-4 2xl:gap-5">
        <MasterResumeEditor
          apiBaseUrl={apiBaseUrl}
          onProfileResumeUploaded={onProfileResumeUploaded}
          profileResume={
            profile.resume_file_name && profile.resume_file_id
              ? {
                  fileName: profile.resume_file_name,
                  fileSize: profile.resume_file_size,
                  fileId: profile.resume_file_id,
                }
              : null
          }
        />
        <div className="grid gap-4 xl:grid-cols-2 2xl:gap-5">
          <ActivityPanel profile={profile} onEditProfile={onEditProfile} />
          <AiMatchProfilePanel
            profile={profile}
            onEditProfile={onEditProfile}
          />
        </div>
        <ExperiencePanel
          profile={profile}
          onAddExperience={onAddExperience}
          onEditExperience={onEditExperience}
          onDeleteExperience={onDeleteExperience}
          onImportExperienceFromCv={onImportExperienceFromCv}
          isExperienceImporting={isExperienceImporting}
          importMessage={experienceImportMessage}
        />
        <SkillsPanel
          profile={profile}
          onEditSkills={onEditSkills}
          onImportSkillsFromCv={onImportSkillsFromCv}
          isSkillsImporting={isSkillsImporting}
          importMessage={skillsImportMessage}
        />
        <EducationPanel
          profile={profile}
          onAddEducation={onAddEducation}
          onEditEducation={onEditEducation}
          onDeleteEducation={onDeleteEducation}
          onImportEducationFromCv={onImportEducationFromCv}
          isEducationImporting={isEducationImporting}
          importMessage={educationImportMessage}
        />
        <PreferencesPanel
          profile={profile}
          onEditPreferences={onEditPreferences}
        />
        <DealbreakersPanel
          profile={profile}
          onEditDealbreakers={onEditDealbreakers}
        />
        <DocumentsPanel
          profile={profile}
          onAddDocument={onAddDocument}
          onEditDocument={onEditDocument}
          onDeleteDocument={onDeleteDocument}
        />
        <AdditionalNotesPanel
          profile={profile}
          onEditAdditionalNotes={onEditAdditionalNotes}
        />
        <ProfileCompletenessPanel profile={profile} />
        <ResumeTemplateManager apiBaseUrl={apiBaseUrl} />
      </div>
    </section>
  );
}

export function ProfileHero({
  profile,
  onEditProfile,
}: {
  profile: CandidateProfile;
  onEditProfile: () => void;
}) {
  const links = getProfileLinks(profile).filter(
    (link) => hasProfileValue(link.value) && link.href,
  );

  return (
    <section className="panel grid shrink-0 overflow-hidden md:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_410px]">
      <div className="relative flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:p-5 2xl:gap-5 2xl:p-6">
        <Button
          variant="ghost"
          className="absolute right-4 top-4 z-10 h-9 rounded-md border border-border bg-[#fff8f1] px-3 text-xs font-bold text-[#1d1e1c] hover:bg-[#fff3e8] sm:right-5 sm:top-5 2xl:h-10 2xl:px-4 2xl:text-[13px]"
          onClick={onEditProfile}
        >
          <Edit3 className="h-4 w-4" />
          Edit Profile
        </Button>
        <div className="relative h-24 w-24 shrink-0 overflow-hidden rounded-full bg-[#fff8f1] ring-1 ring-white/10 2xl:h-28 2xl:w-28">
          <img
            src={profile.avatar_url || defaultCandidateProfile.avatar_url}
            alt={displayProfileValue(profile.name, "Profile avatar")}
            className="h-full w-full object-cover"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[24px] font-bold leading-tight text-foreground 2xl:text-[30px]">
              {displayProfileValue(profile.name, "Set up your profile")}
            </h2>
          </div>
          <p className="mt-2 text-base font-semibold text-[#1d1e1c] 2xl:text-lg">
            {displayProfileValue(profile.current_role, "Add your current role")}
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-sm font-semibold text-muted 2xl:text-base">
            <span>Target role:</span>
            <button
              type="button"
              className="rounded-sm text-left font-bold text-accent transition hover:text-[#e95300] focus:outline-none focus:ring-2 focus:ring-accent/45"
              onClick={onEditProfile}
            >
              {displayProfileValue(
                profile.desired_role,
                "Add the roles you want",
              )}
            </button>
          </p>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[13px] font-medium text-muted 2xl:text-sm">
            <span className="inline-flex items-center gap-1.5">
              <MapPin className="h-4 w-4" />{" "}
              {displayProfileValue(profile.location, "Add location")}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Globe className="h-4 w-4" />{" "}
              {displayProfileValue(
                profile.work_format,
                "Remote, hybrid, onsite",
              )}
            </span>
          </div>
          {hasProfileValue(profile.headline) ? (
            <p className="mt-4 max-w-[720px] text-[13px] leading-5 text-[#4a4a47] 2xl:text-sm 2xl:leading-6">
              {profile.headline}
            </p>
          ) : (
            <div className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-dashed border-border bg-[#fff8f1] p-3">
              <p className="min-w-0 flex-1 text-[13px] leading-5 text-muted">
                Add a short summary so job matching can understand your
                background and goals.
              </p>
              <Button
                variant="ghost"
                className="h-8 rounded-md border border-border px-3 text-xs text-[#1d1e1c] hover:bg-[#fff3e8]"
                onClick={onEditProfile}
              >
                <Plus className="h-4 w-4" />
                Add summary
              </Button>
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-border p-4 md:border-l md:border-t-0 sm:p-5 2xl:p-6">
        <h3 className="text-sm font-bold text-foreground 2xl:text-base">
          Contact & Links
        </h3>
        {links.length > 0 ? (
          <div className="mt-3 grid gap-2.5 2xl:gap-3">
            {links.map((link) => (
              <a
                key={link.label}
                href={link.href}
                target="_blank"
                rel="noreferrer"
                className="grid grid-cols-[36px_minmax(0,1fr)_16px] items-center gap-3 rounded-md border border-transparent p-1.5 transition hover:border-[#c0bbb6] hover:bg-[#fff3e8]"
              >
                <span className="grid h-9 w-9 place-items-center rounded-md border border-border bg-[#fff8f1] text-[#1d1e1c]">
                  <link.icon className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] font-bold text-foreground 2xl:text-sm">
                    {link.label}
                  </span>
                  <span className="block truncate text-xs text-muted 2xl:text-[13px]">
                    {link.value}
                  </span>
                </span>
                <ExternalLink className="h-4 w-4 text-muted" />
              </a>
            ))}
          </div>
        ) : (
          <EmptyProfileState
            className="mt-3"
            title="No links yet"
            description="Add LinkedIn, GitHub, portfolio, or a personal site."
            action="Add links"
            onAction={onEditProfile}
          />
        )}
      </div>
    </section>
  );
}

function EmptyProfileState({
  title,
  description,
  action,
  onAction,
  className,
}: {
  title: string;
  description: string;
  action: string;
  onAction: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-dashed border-border bg-[#fff8f1] p-3",
        className,
      )}
    >
      <p className="text-sm font-bold text-foreground">{title}</p>
      <p className="mt-1 text-xs leading-5 text-muted 2xl:text-[13px]">
        {description}
      </p>
      <Button
        type="button"
        variant="ghost"
        className="mt-3 h-8 rounded-md border border-border bg-transparent px-3 text-xs text-[#1d1e1c] hover:bg-[#fff3e8]"
        onClick={onAction}
      >
        <Plus className="h-4 w-4" />
        {action}
      </Button>
    </div>
  );
}

export function ExperiencePanel({
  profile,
  onAddExperience,
  onEditExperience,
  onDeleteExperience,
  onImportExperienceFromCv,
  isExperienceImporting,
  importMessage,
}: {
  profile: CandidateProfile;
  onAddExperience: () => void;
  onEditExperience: (experience: ExperienceEntry) => void;
  onDeleteExperience: (experienceId: string) => void;
  onImportExperienceFromCv: () => void;
  isExperienceImporting: boolean;
  importMessage: string;
}) {
  const experienceItems = parseExperienceEntries(profile.experience);
  const hasResume =
    hasProfileValue(profile.resume_file_id) &&
    hasProfileValue(profile.resume_file_name);

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-base font-bold 2xl:text-lg">Experience</h2>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-bold text-[#1d1e1c] transition hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:opacity-45 2xl:text-[13px]"
            onClick={onImportExperienceFromCv}
            disabled={!hasResume || isExperienceImporting}
            title={
              hasResume
                ? "Import experience from attached CV"
                : "Attach a CV first"
            }
          >
            <FileText className="h-4 w-4" />
            {isExperienceImporting ? "Importing..." : "Import from CV"}
          </button>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-bold text-accent transition hover:bg-accent/10 hover:text-[#e95300] 2xl:text-[13px]"
            onClick={onAddExperience}
          >
            <Plus className="h-4 w-4" />
            Add Experience
          </button>
        </div>
      </div>
      {importMessage && (
        <p className="mt-3 text-xs font-semibold text-muted 2xl:text-[13px]">
          {importMessage}
        </p>
      )}
      {experienceItems.length > 0 ? (
        <div className="mt-4 space-y-4">
          {experienceItems.map((item) => (
            <article
              key={item.id}
              className="grid grid-cols-[40px_minmax(0,1fr)_auto] gap-3 rounded-md border border-border bg-[#fff8f1] p-3"
            >
              <span className="grid h-10 w-10 place-items-center rounded-md bg-[#fff8f1] text-[#1d1e1c]">
                <BriefcaseBusiness className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h3 className="text-sm font-bold text-foreground 2xl:text-base">
                  {item.title}
                </h3>
                <p className="mt-0.5 text-[13px] font-semibold text-[#1d1e1c] 2xl:text-sm">
                  {item.company}
                </p>
                <p className="mt-1 text-xs text-muted 2xl:text-[13px]">
                  {[item.employment_type, item.location]
                    .filter(Boolean)
                    .join(" • ")}
                </p>
                <p className="mt-1 text-xs text-muted 2xl:text-[13px]">
                  {item.start_date || "Start date"} -{" "}
                  {item.is_current ? "Present" : item.end_date || "End date"}
                </p>
                {item.description && (
                  <p className="mt-2 whitespace-pre-line text-[13px] leading-5 text-muted 2xl:text-sm">
                    {item.description}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  aria-label="Edit experience"
                  onClick={() => onEditExperience(item)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                >
                  <Edit3 className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label="Delete experience"
                  onClick={() => onDeleteExperience(item.id)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#fa5d00]/12 hover:text-[#fa5d00]"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyProfileState
          className="mt-4"
          title="No experience yet"
          description="Add work, internship, freelance, or project experience in a structured format."
          action="Add experience"
          onAction={onAddExperience}
        />
      )}
    </section>
  );
}

export function SkillsPanel({
  profile,
  onEditSkills,
  onImportSkillsFromCv,
  isSkillsImporting,
  importMessage,
}: {
  profile: CandidateProfile;
  onEditSkills: () => void;
  onImportSkillsFromCv: () => void;
  isSkillsImporting: boolean;
  importMessage: string;
}) {
  const skillItems = parseProfileLines(profile.skills);
  const hasResume =
    hasProfileValue(profile.resume_file_id) &&
    hasProfileValue(profile.resume_file_name);
  const skillPreviewLimit = 24;
  const visibleSkillItems = skillItems.slice(0, skillPreviewLimit);
  const hiddenSkillCount = Math.max(
    skillItems.length - visibleSkillItems.length,
    0,
  );

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-bold 2xl:text-lg">Skills</h2>
          {skillItems.length > 0 && (
            <p className="mt-1 text-xs font-medium text-muted 2xl:text-[13px]">
              {skillItems.length} skills available for matching
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-bold text-[#1d1e1c] transition hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:opacity-45 2xl:text-[13px]"
            onClick={onImportSkillsFromCv}
            disabled={!hasResume || isSkillsImporting}
            title={
              hasResume ? "Import skills from attached CV" : "Attach a CV first"
            }
          >
            <FileText className="h-4 w-4" />
            {isSkillsImporting ? "Importing..." : "Import from CV"}
          </button>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-bold text-accent transition hover:bg-accent/10 hover:text-[#e95300] 2xl:text-[13px]"
            onClick={onEditSkills}
          >
            <Edit3 className="h-4 w-4" />
            Edit Skills
          </button>
        </div>
      </div>
      {importMessage && (
        <p className="mt-3 text-xs font-semibold text-muted 2xl:text-[13px]">
          {importMessage}
        </p>
      )}
      {skillItems.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {visibleSkillItems.map((skill) => (
            <span
              key={skill}
              className="inline-flex min-h-7 items-center rounded-md border border-border bg-[#fff8f1] px-2.5 text-xs font-semibold text-[#1d1e1c]"
            >
              {skill}
            </span>
          ))}
          {hiddenSkillCount > 0 && (
            <button
              type="button"
              className="inline-flex min-h-7 items-center rounded-md border border-accent/35 bg-accent/10 px-2.5 text-xs font-bold text-accent transition hover:border-accent/65 hover:bg-accent/15"
              onClick={onEditSkills}
            >
              +{hiddenSkillCount} more
            </button>
          )}
        </div>
      ) : (
        <EmptyProfileState
          className="mt-4"
          title="No skills yet"
          description="Add tools, technologies, languages, and strengths. Use one skill per line."
          action="Add skills"
          onAction={onEditSkills}
        />
      )}
    </section>
  );
}

export function EducationPanel({
  profile,
  onAddEducation,
  onEditEducation,
  onDeleteEducation,
  onImportEducationFromCv,
  isEducationImporting,
  importMessage,
}: {
  profile: CandidateProfile;
  onAddEducation: () => void;
  onEditEducation: (education: EducationEntry) => void;
  onDeleteEducation: (educationId: string) => void;
  onImportEducationFromCv: () => void;
  isEducationImporting: boolean;
  importMessage: string;
}) {
  const educationItems = parseEducationEntries(profile.education);
  const hasResume =
    hasProfileValue(profile.resume_file_id) &&
    hasProfileValue(profile.resume_file_name);

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-base font-bold 2xl:text-lg">
          Education & Certifications
        </h2>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-bold text-[#1d1e1c] transition hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:opacity-45 2xl:text-[13px]"
            onClick={onImportEducationFromCv}
            disabled={!hasResume || isEducationImporting}
            title={
              hasResume
                ? "Import education from attached CV"
                : "Attach a CV first"
            }
          >
            <FileText className="h-4 w-4" />
            {isEducationImporting ? "Importing..." : "Import from CV"}
          </button>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-bold text-accent transition hover:bg-accent/10 hover:text-[#e95300] 2xl:text-[13px]"
            onClick={onAddEducation}
          >
            <Plus className="h-4 w-4" />
            Add Education
          </button>
        </div>
      </div>
      {importMessage && (
        <p className="mt-3 text-xs font-semibold text-muted 2xl:text-[13px]">
          {importMessage}
        </p>
      )}
      {educationItems.length > 0 ? (
        <div className="mt-4 space-y-4">
          {educationItems.map((item) => (
            <article
              key={item.id}
              className="grid grid-cols-[40px_minmax(0,1fr)_auto] gap-3 rounded-md border border-border bg-[#fff8f1] p-3"
            >
              <span className="grid h-10 w-10 place-items-center rounded-md bg-[#fff8f1] text-[#1d1e1c]">
                <GraduationCap className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h3 className="text-sm font-bold text-foreground 2xl:text-base">
                  {item.credential || "Education"}
                </h3>
                <p className="mt-0.5 text-[13px] font-semibold text-[#1d1e1c] 2xl:text-sm">
                  {item.institution || "Institution not specified"}
                </p>
                {(item.field_of_study || item.location) && (
                  <p className="mt-1 text-xs text-muted 2xl:text-[13px]">
                    {[item.field_of_study, item.location]
                      .filter(Boolean)
                      .join(" • ")}
                  </p>
                )}
                {(item.start_date || item.end_date || item.is_current) && (
                  <p className="mt-1 text-xs text-muted 2xl:text-[13px]">
                    {item.start_date || "Start date"} -{" "}
                    {item.is_current ? "Present" : item.end_date || "End date"}
                  </p>
                )}
                {item.description && (
                  <p className="mt-2 whitespace-pre-line text-[13px] leading-5 text-muted 2xl:text-sm">
                    {item.description}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  aria-label="Edit education"
                  onClick={() => onEditEducation(item)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                >
                  <Edit3 className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label="Delete education"
                  onClick={() => onDeleteEducation(item.id)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#fa5d00]/12 hover:text-[#fa5d00]"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyProfileState
          className="mt-4"
          title="No education added"
          description="Add degrees, courses, certifications, or relevant training."
          action="Add education"
          onAction={onAddEducation}
        />
      )}
    </section>
  );
}

export function DocumentsPanel({
  profile,
  onAddDocument,
  onEditDocument,
  onDeleteDocument,
}: {
  profile: CandidateProfile;
  onAddDocument: () => void;
  onEditDocument: (document: DocumentEntry) => void;
  onDeleteDocument: (documentId: string) => void;
}) {
  const documentItems = parseDocumentEntries(profile.documents).filter(
    (item) => item.category !== "Cover Letter",
  );

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-bold 2xl:text-lg">
            Supporting Documents
          </h2>
          <p className="mt-1 text-xs font-medium text-muted 2xl:text-[13px]">
            Store separate English and German CVs, certificates and other
            reusable files.
          </p>
        </div>
        {documentItems.length > 0 && (
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-bold text-accent transition hover:bg-accent/10 hover:text-[#e95300] 2xl:text-[13px]"
            onClick={onAddDocument}
          >
            <Plus className="h-4 w-4" />
            Add Document
          </button>
        )}
      </div>

      {documentItems.length > 0 ? (
        <div className="mt-4 space-y-4">
          {documentItems.map((item) => (
            <article
              key={item.id}
              className="grid grid-cols-[40px_minmax(0,1fr)_auto] gap-3 rounded-md border border-border bg-[#fff8f1] p-3"
            >
              <span className="grid h-10 w-10 place-items-center rounded-md bg-[#fff8f1] text-[#1d1e1c]">
                <FileText className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="min-w-0 text-sm font-bold text-foreground 2xl:text-base">
                    {item.title || item.file_name}
                  </h3>
                  <span className="rounded bg-[#fff8f1] px-2 py-0.5 text-[11px] font-bold text-muted">
                    {item.category}
                  </span>
                  {item.category === "CV / Resume" && item.language ? (
                    <span className="rounded bg-[#fa5d00]/15 px-2 py-0.5 text-[11px] font-bold text-accent">
                      {item.language}
                    </span>
                  ) : null}
                </div>
                {item.issuer && (
                  <p className="mt-0.5 text-[13px] font-semibold text-[#1d1e1c] 2xl:text-sm">
                    {item.issuer}
                  </p>
                )}
                <p className="mt-1 truncate text-xs text-muted 2xl:text-[13px]">
                  {item.file_name}
                  {item.file_size ? ` • ${item.file_size}` : ""}
                  {item.uploaded_at
                    ? ` • ${formatProfileDate(item.uploaded_at)}`
                    : ""}
                </p>
                {item.notes && (
                  <p className="mt-2 whitespace-pre-line text-[13px] leading-5 text-muted 2xl:text-sm">
                    {item.notes}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <a
                  aria-label="Download document"
                  href={item.download_url}
                  download={item.file_name || item.title}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                >
                  <Download className="h-4 w-4" />
                </a>
                <button
                  type="button"
                  aria-label="Edit document"
                  onClick={() => onEditDocument(item)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
                >
                  <Edit3 className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label="Delete document"
                  onClick={() => onDeleteDocument(item.id)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#fa5d00]/12 hover:text-[#fa5d00]"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyProfileState
          className="mt-4"
          title="No application documents yet"
          description="Add CV versions, certificates and other reusable documents. Cover letters are generated from the built-in template."
          action="Add document"
          onAction={onAddDocument}
        />
      )}
    </section>
  );
}

export function ActivityPanel({
  profile,
  onEditProfile,
}: {
  profile: CandidateProfile;
  onEditProfile: () => void;
}) {
  const completion = getProfileCompletion(profile);

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-bold 2xl:text-lg">Profile Snapshot</h2>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 border border-border px-2 text-[11px] text-[#1d1e1c]"
          onClick={onEditProfile}
        >
          Edit
        </Button>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <MiniMetric
          icon={FileText}
          value={parseExperienceEntries(profile.experience).length.toString()}
          label="Experience"
          color="blue"
        />
        <MiniMetric
          icon={Star}
          value={parseProfileLines(profile.skills).length.toString()}
          label="Skills"
          color="orange"
        />
        <MiniMetric
          icon={Globe}
          value={getProfileLinks(profile)
            .filter((link) => hasProfileValue(link.value) && link.href)
            .length.toString()}
          label="Links"
          color="green"
        />
      </div>
      <div className="mt-4 rounded-md border border-border bg-[#fff8f1] p-3">
        <div className="flex items-end gap-3">
          <p className="text-[28px] font-bold leading-none text-foreground">
            {completion}%
          </p>
          <p className="pb-1 text-xs font-medium text-muted">
            Profile completeness
          </p>
        </div>
        <div className="mt-3 h-2 rounded-full bg-[#fff8f1]">
          <div
            className="h-full rounded-full bg-success"
            style={{ width: `${completion}%` }}
          />
        </div>
        <p className="mt-2 text-xs font-medium text-muted">
          {completion < 50
            ? "Add basics, experience, and skills to improve matching."
            : "Profile has enough signal for better matching."}
        </p>
      </div>
    </section>
  );
}

export function AiMatchProfilePanel({
  profile,
  onEditProfile,
}: {
  profile: CandidateProfile;
  onEditProfile: () => void;
}) {
  const matchProfile = getAiMatchProfile(profile);
  const hasSignals = matchProfile.signals.length > 0;

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex items-center gap-2.5">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-[#fa5d00]/20 text-sm font-black text-accent">
          AI
        </span>
        <h2 className="text-base font-bold 2xl:text-lg">AI Match Profile</h2>
      </div>
      {hasSignals ? (
        <div className="mt-4 divide-y divide-border rounded-md border border-border">
          <AiProfileGroup
            title="Signals"
            icon={Check}
            iconClassName="text-success"
            items={matchProfile.signals}
          />
          {matchProfile.gaps.length > 0 ? (
            <AiProfileGroup
              title="Next gaps"
              icon={CircleDot}
              iconClassName="text-[#fa5d00]"
              items={matchProfile.gaps}
            />
          ) : (
            <AiProfileGroup
              title="Ready for matching"
              icon={Check}
              iconClassName="text-success"
              items={["Profile has enough structured signal for job matching"]}
            />
          )}
        </div>
      ) : (
        <EmptyProfileState
          className="mt-4"
          title="Not enough profile signal"
          description="Add your current role, target role, and a few skills to unlock useful match analysis."
          action="Add profile signal"
          onAction={onEditProfile}
        />
      )}
    </section>
  );
}

export function PreferencesPanel({
  profile,
  onEditPreferences,
}: {
  profile: CandidateProfile;
  onEditPreferences: () => void;
}) {
  const preferences = parseJobPreferences(profile.job_preferences);
  const preferenceSummary = formatPreferenceSummary(preferences);

  return (
    <section className="panel p-4 2xl:p-5">
      <ProfileSectionHeader
        title="Job Preferences"
        action="Edit Preferences"
        onAction={onEditPreferences}
      />
      {preferenceSummary.length > 0 ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {preferenceSummary.map((group) => (
            <div
              key={group.label}
              className={cn(
                "rounded-md border border-border bg-[#fff8f1] p-3",
                group.label === "Notes" && "md:col-span-2",
              )}
            >
              <p className="text-[11px] font-bold uppercase tracking-normal text-muted">
                {group.label}
              </p>
              {group.label === "Notes" ? (
                <p className="mt-2 whitespace-pre-line text-[13px] leading-5 text-[#1d1e1c]">
                  {group.values.join("\n")}
                </p>
              ) : (
                <div className="mt-2 flex flex-wrap gap-2">
                  {group.values.map((value) => (
                    <span
                      key={value}
                      className="inline-flex min-h-7 items-center rounded-md border border-border bg-[#fff8f1] px-2.5 text-xs font-semibold text-[#1d1e1c]"
                    >
                      {value}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <EmptyProfileState
          className="mt-4"
          title="No preferences set"
          description="Add desired roles, industries, countries, salary range, visa needs, or work format."
          action="Add preferences"
          onAction={onEditPreferences}
        />
      )}
    </section>
  );
}

export function DealbreakersPanel({
  profile,
  onEditDealbreakers,
}: {
  profile: CandidateProfile;
  onEditDealbreakers: () => void;
}) {
  const dealbreakers = parseProfileLines(profile.dealbreakers);

  return (
    <section className="panel p-4 2xl:p-5">
      <ProfileSectionHeader
        title="Dealbreakers"
        action="Edit Dealbreakers"
        onAction={onEditDealbreakers}
      />
      {dealbreakers.length > 0 ? (
        <div className="mt-4 space-y-2.5">
          {dealbreakers.map((item) => (
            <p
              key={item}
              className="flex items-center gap-2 text-[13px] text-muted 2xl:text-sm"
            >
              <Ban className="h-4 w-4 text-[#fa5d00]" />
              {item}
            </p>
          ))}
        </div>
      ) : (
        <EmptyProfileState
          className="mt-4"
          title="No dealbreakers"
          description="No hard limits are set. This is valid if every matching condition is flexible."
          action="Edit dealbreakers"
          onAction={onEditDealbreakers}
        />
      )}
    </section>
  );
}

export function AdditionalNotesPanel({
  profile,
  onEditAdditionalNotes,
}: {
  profile: CandidateProfile;
  onEditAdditionalNotes: () => void;
}) {
  return (
    <section className="panel p-4 2xl:p-5">
      <ProfileSectionHeader
        title="Additional Notes"
        action="Edit Notes"
        onAction={onEditAdditionalNotes}
      />
      {hasProfileValue(profile.additional_notes) ? (
        <div className="mt-4 whitespace-pre-line rounded-md border border-border bg-[#fff8f1] p-3 text-[13px] leading-5 text-[#1d1e1c]">
          {profile.additional_notes}
        </div>
      ) : (
        <EmptyProfileState
          className="mt-4"
          title="No notes"
          description="Add context that does not fit elsewhere: availability, motivation, constraints, or personal positioning."
          action="Add notes"
          onAction={onEditAdditionalNotes}
        />
      )}
    </section>
  );
}

export function ProfileCompletenessPanel({
  profile,
}: {
  profile: CandidateProfile;
}) {
  const completionItems = getProfileCompletionItems(profile);
  const missingItems = completionItems.filter((item) => !item.complete);
  const completedCount = completionItems.length - missingItems.length;
  const visibleMissingItems = missingItems.slice(0, 5);

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-bold 2xl:text-lg">Profile Readiness</h2>
          <p className="mt-1 text-xs font-medium text-muted 2xl:text-[13px]">
            {completedCount} of {completionItems.length} matching signals are
            complete
          </p>
        </div>
        <span
          className={cn(
            "inline-flex min-h-8 items-center self-start rounded-md border px-2.5 text-xs font-bold",
            missingItems.length === 0
              ? "border-success/40 bg-success/12 text-success"
              : "border-[#fa5d00]/35 bg-[#fa5d00]/10 text-accent",
          )}
        >
          {missingItems.length === 0
            ? "Ready"
            : `${missingItems.length} next step${missingItems.length === 1 ? "" : "s"}`}
        </span>
      </div>
      {missingItems.length === 0 ? (
        <div className="mt-4 rounded-md border border-success/25 bg-success/10 p-3">
          <p className="text-sm font-bold text-foreground">
            Profile has enough signal for matching
          </p>
          <p className="mt-1 text-xs leading-5 text-muted 2xl:text-[13px]">
            Keep it fresh when your resume, target roles, or application
            constraints change.
          </p>
        </div>
      ) : (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {visibleMissingItems.map((item) => (
            <div
              key={item.label}
              className="flex items-start gap-2 rounded-md border border-border bg-[#fff8f1] p-3"
            >
              <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-[#fa5d00]" />
              <div className="min-w-0">
                <p className="text-xs font-bold text-foreground 2xl:text-[13px]">
                  {item.label}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted">
                  {item.action}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ProfileSectionHeader({
  title,
  action,
  onAction,
}: {
  title: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-base font-bold 2xl:text-lg">{title}</h2>
      <button
        type="button"
        className="text-xs font-bold text-accent transition hover:text-[#e95300] 2xl:text-[13px]"
        onClick={onAction}
      >
        {action}
      </button>
    </div>
  );
}

function MiniMetric({
  icon: Icon,
  value,
  label,
  color,
}: {
  icon: typeof FileText;
  value: string;
  label: string;
  color: "blue" | "orange" | "green";
}) {
  return (
    <div className="rounded-md border border-border bg-[#fff8f1] p-3">
      <Icon
        className={cn(
          "h-5 w-5",
          color === "blue"
            ? "text-[#fa5d00]"
            : color === "green"
              ? "text-success"
              : "text-accent",
        )}
      />
      <p className="mt-2 text-xl font-bold leading-none text-foreground">
        {value}
      </p>
      <p className="mt-1 text-[11px] text-muted">{label}</p>
    </div>
  );
}

function AiProfileGroup({
  title,
  items,
  icon: Icon,
  iconClassName,
}: {
  title: string;
  items: string[];
  icon: typeof Check;
  iconClassName: string;
}) {
  return (
    <div className="p-3">
      <h3 className="text-[13px] font-bold text-foreground">{title}</h3>
      <ul className="mt-2 space-y-1.5 text-[13px] text-muted">
        {items.map((item) => (
          <li key={item} className="flex items-center gap-2">
            <Icon className={cn("h-4 w-4", iconClassName)} />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
