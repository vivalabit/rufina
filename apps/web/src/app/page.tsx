"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import {
  Archive,
  ArchiveRestore,
  Ban,
  BarChart3,
  Bookmark,
  BrainCircuit,
  BriefcaseBusiness,
  Bot,
  Calendar,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  Cloud,
  Code2,
  Copy,
  Database,
  Download,
  Edit3,
  Eye,
  ExternalLink,
  FileText,
  FlaskConical,
  Github,
  GraduationCap,
  Globe,
  Home,
  KeyRound,
  Linkedin,
  Mail,
  MapPin,
  MoreHorizontal,
  Palette,
  Plus,
  Info,
  RotateCcw,
  Save,
  Search,
  Send,
  Server,
  Share2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Smartphone,
  Star,
  Settings,
  Target,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  AssistantView,
  type AssistantAppliedAction,
  type AssistantDocumentAttachment,
  type AssistantLaunch,
} from "@/components/assistant-view";
import { ApplicationWorkspace } from "@/components/application-workspace";
import { DashboardGreeting, useHydrationSafeCurrentTime } from "@/components/dashboard-greeting";
import {
  JobsToolbar,
  type BulkAnalysisScope,
} from "@/components/jobs-toolbar";
import { MasterResumeEditor } from "@/components/master-resume-editor";
import { ResumeTemplateManager } from "@/components/resume-template-manager";
import { getAiMatchAnalysisStatus, legacyAiMatchVersion } from "@/lib/ai-match";
import { getAiSourceLabel, type AiBackend, type AiSource } from "@/lib/ai-source";
import { findWorkspaceApplication, getHashForView, getRouteFromHash, type View } from "@/lib/app-route";
import { cn } from "@/lib/utils";

type AiMatchMetadata = {
  version: string;
  revision?: string;
  fingerprint?: string;
  cacheKey: string;
  source: AiSource;
  backend?: AiSource;
  score: number;
  confidence: "low" | "medium" | "high";
  breakdown: Record<string, number>;
  reasons: string[];
  gaps: string[];
  applicationGuide?: {
    language: "English" | "German";
    positioning: string;
    readiness?: "ready" | "needs_confirmation" | "weak_fit";
    roleMission?: string;
    hiringPriorities?: string[];
    mustHave?: string[];
    niceToHave?: string[];
    hardConstraints?: string[];
    evidenceMatrix?: Array<{
      requirement: string;
      importance: "required" | "preferred";
      status: "verified" | "transferable" | "needs_confirmation" | "missing";
      evidence: string;
      action: string;
      sourceIds?: string[];
      sources?: Array<{ id: string; label: string; excerpt: string }>;
    }>;
    clarificationQuestions?: Array<{
      id: string;
      requirement: string;
      question: string;
      why: string;
      claimIfConfirmed: string;
      blocking: boolean;
    }>;
    resumePlan?: {
      targetHeadline: string;
      summaryFocus: string;
      evidenceToLead: string[];
      bulletStrategy: string[];
    };
    coverLetterPlan?: {
      openingAngle: string;
      proofPoints: string[];
      motivationAngle: string;
    };
    cvImprovements: string[];
    coverLetterStrategy: string[];
    risks: string[];
    keywords: string[];
    applicationQuestions: string[];
    finalChecklist: string[];
  };
  explanation?: string;
  rawExplanation?: string;
  heuristicScore?: number;
  updatedAt?: string;
  providerError?: string;
  feedback?: MatchFeedback;
  calibration?: {
    feedback: MatchFeedback;
    adjustment: number;
  };
};

type MatchFeedback = "good_match" | "bad_match" | "not_interested";

type JobRecommendation = {
  text: string;
  gain: string;
  why?: string;
  impact?: string;
  action?: string;
};

type Job = {
  id: string;
  company: string;
  title: string;
  location: string;
  type: string;
  salary: string;
  posted: string;
  experience: string;
  department: string;
  match: number;
  logo: "stripe" | "figma" | "linkedin" | "indeed" | "jobs_ch" | "manual";
  overview: string;
  responsibilities: string[];
  requirements: string[];
  skills: string[];
  salaryAverage: string;
  salaryMin: string;
  salaryMax: string;
  recommendations: JobRecommendation[];
  companyInfo: string;
  reviews: string[];
  similarJobs: string[];
  applyUrl?: string;
  sourceUrl?: string;
  addedAt?: string;
  archived?: boolean;
  archivedAt?: string;
  aiMatch?: AiMatchMetadata;
};

type AiMatchJobStatus = {
  runId: string;
  status: "idle" | "queued" | "running" | "completed" | "failed";
  total: number;
  processed: number;
  updatedJobs: Array<{ id: string; data: unknown }>;
  failedJobs?: Array<{ id: string; error: string }>;
  error?: string | null;
};

type ApplicationStatus = "draft" | "applied" | "interview" | "assessment" | "offer" | "rejected";
type ApplicationEventType = "screening" | "interview" | "assessment" | "follow_up" | "offer_deadline";
type ApplicationEventStatus = "scheduled" | "completed" | "canceled";
type ApplicationEventOutcome = "positive" | "negative" | "neutral";

type ApplicationDocument = {
  id: string;
  artifactId?: string;
  title: string;
  fileName: string;
  fileSize: string;
  fileType: string;
  uploadedAt: string;
  dataUrl: string;
};

type TrackedApplication = {
  id: string;
  job: Job;
  status: ApplicationStatus;
  appliedAt: string;
  nextStep: string;
  notes: string;
  documents: ApplicationDocument[];
};

type ManualJobDraft = {
  title: string;
  company: string;
  location: string;
  applyUrl: string;
  overview: string;
};

type ManualApplicationDraft = ManualJobDraft & {
  status: ApplicationStatus;
  documents: ApplicationDocument[];
};

type ApplicationEvent = {
  id: string;
  applicationId: string;
  type: ApplicationEventType;
  status: ApplicationEventStatus;
  outcome?: ApplicationEventOutcome;
  title: string;
  startsAt: string;
  durationMinutes: number;
  timezone: string;
  location: string;
  notes: string;
};

type ApplicationEventDraft = {
  type: ApplicationEventType;
  id?: string;
  status: ApplicationEventStatus;
  outcome: ApplicationEventOutcome | "";
  title: string;
  startsAt: string;
  durationMinutes: string;
  timezone: string;
  location: string;
  notes: string;
};

type ApplicationTimelineItem = {
  label: string;
  date: string;
  state: "done" | "current" | "future" | "canceled" | "rejected";
  event?: ApplicationEvent;
};

type AIBackendName = AiBackend;
type OpenAIReasoningEffort = "none" | "low" | "medium" | "high" | "xhigh" | "max";
type AIWorkloadReasoningEffort = "off" | OpenAIReasoningEffort;

type AppSettings = {
  has_brightdata_api_key: boolean;
  brightdata_api_key_preview: string;
  ai_backend: AIBackendName;
  openai_api_key_configured: boolean;
  openai_api_key_preview: string;
  openai_api_model: string;
  openai_api_reasoning_effort: OpenAIReasoningEffort;
  openai_api_timeout_seconds: number;
  openai_api_max_attempts: number;
  openai_api_retry_backoff_seconds: number;
  ai_match_model: string;
  ai_match_reasoning: AIWorkloadReasoningEffort;
  ai_match_batch_size: number;
  ai_match_timeout_seconds: number;
  ai_match_max_attempts: number;
  job_screening_model: string;
  job_screening_reasoning: AIWorkloadReasoningEffort;
  job_screening_batch_size: number;
  job_screening_timeout_seconds: number;
  job_screening_max_attempts: number;
  job_screening_max_description_chars: number;
};

type AppSettingsUpdate = Partial<{
  brightdata_api_key: string;
  ai_backend: AIBackendName;
  openai_api_key: string;
  openai_api_model: string;
  openai_api_reasoning_effort: OpenAIReasoningEffort;
  openai_api_timeout_seconds: number;
  openai_api_max_attempts: number;
  openai_api_retry_backoff_seconds: number;
  ai_match_model: string;
  ai_match_reasoning: AIWorkloadReasoningEffort;
  ai_match_batch_size: number;
  ai_match_timeout_seconds: number;
  ai_match_max_attempts: number;
  job_screening_model: string;
  job_screening_reasoning: AIWorkloadReasoningEffort;
  job_screening_batch_size: number;
  job_screening_timeout_seconds: number;
  job_screening_max_attempts: number;
  job_screening_max_description_chars: number;
}>;

const defaultAppSettings: AppSettings = {
  has_brightdata_api_key: false,
  brightdata_api_key_preview: "",
  ai_backend: "openclaw_codex",
  openai_api_key_configured: false,
  openai_api_key_preview: "",
  openai_api_model: "gpt-5.6-terra",
  openai_api_reasoning_effort: "medium",
  openai_api_timeout_seconds: 120,
  openai_api_max_attempts: 2,
  openai_api_retry_backoff_seconds: 0.8,
  ai_match_model: "openai/gpt-5.6-terra",
  ai_match_reasoning: "low",
  ai_match_batch_size: 1,
  ai_match_timeout_seconds: 120,
  ai_match_max_attempts: 2,
  job_screening_model: "openai/gpt-5-mini",
  job_screening_reasoning: "off",
  job_screening_batch_size: 10,
  job_screening_timeout_seconds: 60,
  job_screening_max_attempts: 2,
  job_screening_max_description_chars: 12_000,
};

type BrightDataApiKeyResponse = {
  brightdata_api_key?: string;
  detail?: string;
};

type UiSettings = {
  showLogs: boolean;
};

type AppLogLevel = "info" | "success" | "warning" | "error";

type AppLogEntry = {
  id: string;
  timestamp: string;
  level: AppLogLevel;
  area: string;
  message: string;
  details?: string;
};

type ParserId = "linkedin" | "indeed" | "jobs_ch";

type ParserSearchForm = {
  parsers: ParserId[];
  keywords: string;
  location: string;
  remote: string;
  experienceLevel: string;
  jobType: string;
  datePosted: string;
  resultsLimit: string;
  country: string;
  deduplicate: boolean;
  searchName: string;
  folder: string;
};

type JobFilterKey = "location" | "remote" | "salary" | "experience" | "type" | "match";

type JobFilters = Record<JobFilterKey, string>;

type JobSortBy = "AI Match" | "Time" | "Salary";

type ParserSearchConfig = {
  id: string;
  name: string;
  form: ParserSearchForm;
  filters: Record<string, unknown>;
  updatedAt: string;
};

type JobSearchConfigPayload = {
  id: string;
  name: string;
  filters: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

type JobSearchRunPayload = {
  status: string;
  jobsFound: number;
  jobsAlreadyKnown: number;
  jobsScreened: number;
  jobsPassed: number;
  jobsRejected: number;
  jobsUncertain: number;
  jobsAdded: number;
  jobsAnalyzed: number;
  screeningErrors: number;
  sourceErrors: Record<string, string>;
  warning?: string | null;
};

type CandidateProfile = {
  avatar_url: string;
  name: string;
  current_role: string;
  desired_role: string;
  location: string;
  work_format: string;
  headline: string;
  linkedin: string;
  github: string;
  portfolio: string;
  personal_site: string;
  experience: string;
  skills: string;
  education: string;
  job_preferences: string;
  dealbreakers: string;
  additional_notes: string;
  documents: string;
  resume_file_name: string;
  resume_file_size: string;
  resume_updated_at: string;
  resume_data_url: string;
};

type ExperienceEntry = {
  id: string;
  title: string;
  company: string;
  employment_type: string;
  location: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  description: string;
};

type EducationEntry = {
  id: string;
  institution: string;
  credential: string;
  field_of_study: string;
  location: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  description: string;
};

type DocumentEntry = {
  id: string;
  title: string;
  category: string;
  language: string;
  issuer: string;
  notes: string;
  file_name: string;
  file_size: string;
  file_type: string;
  uploaded_at: string;
  data_url: string;
};

type JobPreferences = {
  desired_roles: string[];
  seniority: string[];
  locations: string[];
  work_formats: string[];
  employment_types: string[];
  industries: string[];
  salary_min: string;
  salary_currency: string;
  work_authorization: string;
  swiss_permit_status: string;
  languages: string[];
  company_sizes: string[];
  priorities: string[];
  notes: string;
  no_preference: PreferenceAnyField[];
};

type PreferenceListField = "desired_roles" | "locations" | "industries" | "languages";
type PreferenceToggleField = "seniority" | "work_formats" | "employment_types" | "company_sizes" | "priorities";
type PreferenceAnyField =
  | PreferenceListField
  | PreferenceToggleField
  | "salary"
  | "work_authorization";
type PreferenceInputs = Record<PreferenceListField, string>;

type ResumeExperienceImportResponse = {
  experience?: Array<Partial<ExperienceEntry>>;
  message?: string;
  detail?: string;
};

type ResumeEducationImportResponse = {
  education?: Array<Partial<EducationEntry>>;
  message?: string;
  detail?: string;
};

type ResumeSkillsImportResponse = {
  skills?: string[];
  message?: string;
  detail?: string;
};

const jobs: Job[] = [
  {
    id: "stripe-senior-product-designer",
    company: "Stripe",
    title: "Senior Product Designer",
    location: "Remote",
    type: "Full-time",
    salary: "$120k - $160k",
    posted: "2h ago",
    experience: "5+ years",
    department: "Product Design",
    match: 92,
    logo: "stripe",
    overview:
      "We're looking for a Senior Product Designer to join our team and help design the future of online payments. You'll work on complex problems that impact millions of businesses worldwide.",
    responsibilities: [
      "Lead design projects from concept to execution",
      "Collaborate with cross-functional teams",
      "Design user-centered solutions for complex problems",
      "Mentor junior designers",
    ],
    requirements: [
      "5+ years of product design experience",
      "Strong portfolio demonstrating design thinking",
      "Experience with design systems",
      "Excellent communication skills",
    ],
    skills: ["Figma", "Sketch", "Design Systems", "User Research", "Prototyping"],
    salaryAverage: "$140k",
    salaryMin: "$120k",
    salaryMax: "$160k",
    recommendations: [],
    companyInfo:
      "Stripe builds financial infrastructure for internet businesses, with design teams focused on developer tools, dashboards, and payment experiences.",
    reviews: [
      "Design quality bar is high and feedback cycles are direct.",
      "Strong product culture with close engineering collaboration.",
    ],
    similarJobs: ["Staff Product Designer at Square", "Design Systems Lead at Ramp", "Senior UX Designer at Shopify"],
  },
  {
    id: "figma-product-design-lead",
    company: "Figma",
    title: "Product Design Lead",
    location: "Remote",
    type: "Full-time",
    salary: "$130k - $170k",
    posted: "5h ago",
    experience: "6+ years",
    department: "Editor Experience",
    match: 89,
    logo: "figma",
    overview:
      "Figma is hiring a Product Design Lead to shape collaborative creation workflows for designers, engineers, and product teams. This role owns strategy, craft, and team rituals for high-impact editor surfaces.",
    responsibilities: [
      "Define the product design direction for core collaboration flows",
      "Partner with research, product, and engineering leads",
      "Prototype new interaction models",
      "Coach designers through critiques and launches",
    ],
    requirements: [
      "6+ years designing creative or productivity tools",
      "Experience leading ambiguous product initiatives",
      "Strong systems thinking and interaction design craft",
      "Comfort presenting design rationale to leadership",
    ],
    skills: ["Figma", "Prototyping", "Design Strategy", "Research", "Collaboration"],
    salaryAverage: "$150k",
    salaryMin: "$130k",
    salaryMax: "$170k",
    recommendations: [],
    companyInfo:
      "Figma creates collaborative design and product development software used by teams to ideate, design, prototype, and ship together.",
    reviews: [
      "Fast-moving product teams with thoughtful design critique.",
      "Strong remote culture and high ownership expectations.",
    ],
    similarJobs: ["Principal Product Designer at Miro", "Design Lead at Linear", "Senior Product Designer at Webflow"],
  },
];

const tabs = ["Overview", "Company", "AI Match", "Reviews", "Similar Jobs"];
type ParserSearchStatus = "idle" | "loading" | "ready" | "error";

const applicationStatuses: Array<{ status: ApplicationStatus; label: string }> = [
  { status: "draft", label: "Preparing" },
  { status: "applied", label: "Applied" },
  { status: "interview", label: "Interview" },
  { status: "assessment", label: "Assessment" },
  { status: "offer", label: "Offer" },
  { status: "rejected", label: "Rejected" },
];
const trackedApplicationStatuses = applicationStatuses.filter((item) => item.status !== "draft");

const applicationStatusStyles: Record<ApplicationStatus, string> = {
  draft: "border-[#9f7aea]/40 bg-[#9f7aea]/14 text-[#c4a7ff]",
  applied: "border-accent/35 bg-accent/12 text-accent",
  interview: "border-success/35 bg-success/12 text-success",
  assessment: "border-[#2f80ed]/40 bg-[#2f80ed]/14 text-[#8cc7ff]",
  offer: "border-success/45 bg-success/18 text-success",
  rejected: "border-[#d94d4d]/45 bg-[#d94d4d]/13 text-[#ff8a8a]",
};

const applicationEventTypes: Array<{ type: ApplicationEventType; label: string }> = [
  { type: "screening", label: "Screening" },
  { type: "interview", label: "Interview" },
  { type: "assessment", label: "Assessment deadline" },
  { type: "follow_up", label: "Follow-up" },
  { type: "offer_deadline", label: "Offer deadline" },
];

const applicationEventStatuses: Array<{ status: ApplicationEventStatus; label: string }> = [
  { status: "scheduled", label: "Scheduled" },
  { status: "completed", label: "Completed" },
  { status: "canceled", label: "Canceled" },
];

const applicationEventOutcomes: Array<{ outcome: ApplicationEventOutcome; label: string }> = [
  { outcome: "positive", label: "Positive" },
  { outcome: "neutral", label: "Neutral" },
  { outcome: "negative", label: "Rejected" },
];

const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const aiMatchStatusPollDelayMs = 2500;
const aiMatchStatusPollMaxAttempts = 720;
const recentJobWindowMs = 24 * 60 * 60 * 1000;
const importedJobsStorageKey = "tasko.importedJobs.v1";
const savedJobIdsStorageKey = "tasko.savedJobIds.v1";
const archivedJobIdsStorageKey = "tasko.archivedJobIds.v1";
const deletedJobIdsStorageKey = "tasko.deletedJobIds.v1";
const applicationsStorageKey = "tasko.applications.v1";
const legacyDemoApplicationIds = new Set([
  "application-stripe-senior-product-designer",
  "application-figma-product-design-lead",
]);
const applicationEventsStorageKey = "tasko.applicationEvents.v1";
const profileStorageKey = "tasko.profile.v1";
const legacyParserSearchConfigsStorageKey = "tasko.parserSearchConfigs.v1";
const parserSearchConfigsStorageKey = "tasko.parserSearchConfigs.v2";
const uiSettingsStorageKey = "tasko.uiSettings.v1";
const appLogsStorageKey = "tasko.appLogs.v1";
const screenshotSessionId =
  process.env.NEXT_PUBLIC_SCREENSHOT_SESSION_ID?.trim() ?? "";
const screenshotSessionStorageKey = "rufina.screenshotSessionId";
const legacyMovedFromJobsNote = "Moved from Jobs after applying.";
const maxStoredAppLogs = 300;

const assistantPrompts = {
  whyMatch: (score: number) =>
    `Why ${score}%? Explain this rating using the selected vacancy and my verified profile: show what raises the score, what lowers it, and which requirements are missing or only partially supported. End with a prioritized "How to improve the match" section containing concrete actions I can take before applying. Separate resume/presentation improvements from genuinely missing experience or skills, and do not invent evidence.`,
  whyNoMatch:
    "Explain why this vacancy does not have a match score yet and what information or analysis is needed to assess it against my profile.",
  beforeApplying:
    "Tell me what I need to know before applying to this vacancy. Prioritize must-have requirements, hard constraints, missing or transferable evidence, likely recruiter concerns, facts I should verify, and a clear recommendation on whether and how to apply. Use only the vacancy and verified profile evidence.",
  followUpApplication: "Write a concise recruiter follow-up for this application based on its current status, next step, and notes.",
  prepareInterview: "Prepare me for an interview for this role with likely questions, answer guidance, verified evidence to use, and questions to ask.",
  improveProfile: "Review my candidate profile and give me a prioritized, evidence-based improvement plan. Identify missing or weak sections and rewrite my headline and summary without inventing facts.",
} as const;

const defaultParserSearchForm: ParserSearchForm = {
  parsers: ["linkedin"],
  keywords: "",
  location: "",
  remote: "Any",
  experienceLevel: "Any",
  jobType: "Any",
  datePosted: "Any time",
  resultsLimit: "10",
  country: "Any",
  deduplicate: true,
  searchName: "",
  folder: "",
};

const defaultJobFilters: JobFilters = {
  location: "Any",
  remote: "Any",
  salary: "Any",
  experience: "Any",
  type: "Any",
  match: "Any",
};

const remoteFilterOptions = [
  { value: "remote", label: "Remote only" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
];

const salaryFilterOptions = [
  { value: "listed", label: "Salary listed" },
  { value: "100000", label: "$100k+" },
  { value: "120000", label: "$120k+" },
  { value: "140000", label: "$140k+" },
];

const experienceFilterOptions = [
  { value: "entry", label: "Entry / Junior" },
  { value: "mid", label: "Mid-level" },
  { value: "senior", label: "Senior+" },
];

const matchFilterOptions = [
  { value: "70", label: "70%+" },
  { value: "80", label: "80%+" },
  { value: "90", label: "90%+" },
];

const jobSortOptions: JobSortBy[] = ["AI Match", "Time", "Salary"];

const jobFilterWidths: Record<JobFilterKey, string> = {
  location: "w-[112px] 2xl:w-[136px]",
  remote: "w-[96px] 2xl:w-[136px]",
  salary: "w-[96px] 2xl:w-[136px]",
  experience: "w-[126px] 2xl:w-[136px]",
  type: "w-[118px] 2xl:w-[136px]",
  match: "w-[118px] 2xl:w-[136px]",
};

const defaultUiSettings: UiSettings = {
  showLogs: false,
};

const navItems: Array<{ label: string; icon: typeof Home; href: string; view?: View }> = [
  { label: "Dashboard", icon: Home, href: "#dashboard", view: "Dashboard" },
  { label: "Jobs", icon: BriefcaseBusiness, href: "#jobs", view: "Jobs" },
  { label: "Applications", icon: Mail, href: "#applications", view: "Applications" },
  { label: "Calendar", icon: CalendarDays, href: "#calendar", view: "Calendar" },
  { label: "AI Assistant", icon: Sparkles, href: "#assistant", view: "Assistant" },
];

const defaultCandidateProfile: CandidateProfile = {
  avatar_url: "/avatars/default-pug.png",
  name: "",
  current_role: "",
  desired_role: "",
  location: "",
  work_format: "",
  headline: "",
  linkedin: "",
  github: "",
  portfolio: "",
  personal_site: "",
  experience: "",
  skills: "",
  education: "",
  job_preferences: "",
  dealbreakers: "",
  additional_notes: "",
  documents: "",
  resume_file_name: "",
  resume_file_size: "",
  resume_updated_at: "",
  resume_data_url: "",
};

const candidateProfileDataFields = Object.keys(defaultCandidateProfile).filter(
  (field) => field !== "avatar_url",
) as Array<keyof CandidateProfile>;

const defaultExperienceDraft: ExperienceEntry = {
  id: "",
  title: "",
  company: "",
  employment_type: "Full-time",
  location: "",
  start_date: "",
  end_date: "",
  is_current: false,
  description: "",
};

const defaultEducationDraft: EducationEntry = {
  id: "",
  institution: "",
  credential: "",
  field_of_study: "",
  location: "",
  start_date: "",
  end_date: "",
  is_current: false,
  description: "",
};

const defaultDocumentDraft: DocumentEntry = {
  id: "",
  title: "",
  category: "Other",
  language: "",
  issuer: "",
  notes: "",
  file_name: "",
  file_size: "",
  file_type: "",
  uploaded_at: "",
  data_url: "",
};

const defaultManualApplicationDraft: ManualApplicationDraft = {
  title: "",
  company: "",
  location: "",
  applyUrl: "",
  overview: "",
  status: "applied",
  documents: [],
};

const defaultManualJobDraft: ManualJobDraft = {
  title: "",
  company: "",
  location: "",
  applyUrl: "",
  overview: "",
};

const documentCategories = [
  "CV / Resume",
  "Diploma",
  "Certificate",
  "Recommendation",
  "Work permit",
  "Portfolio",
  "Transcript",
  "Other",
];

const defaultJobPreferences: JobPreferences = {
  desired_roles: [],
  seniority: [],
  locations: [],
  work_formats: [],
  employment_types: [],
  industries: [],
  salary_min: "",
  salary_currency: "CHF",
  work_authorization: "",
  swiss_permit_status: "",
  languages: [],
  company_sizes: [],
  priorities: [],
  notes: "",
  no_preference: [],
};

const defaultPreferenceInputs: PreferenceInputs = {
  desired_roles: "",
  locations: "",
  industries: "",
  languages: "",
};

const preferenceOptions = {
  seniority: ["Intern", "Entry-level", "Junior", "Mid-level", "Senior"],
  work_formats: ["Remote", "Hybrid", "On-site", "Relocation"],
  employment_types: ["Full-time", "Part-time", "Internship", "Contract", "Freelance"],
  company_sizes: ["Startup", "Scale-up", "Mid-size", "Enterprise"],
  priorities: ["Salary", "Learning", "Remote", "Relocation", "Tech stack", "Stability", "Fast hiring"],
  work_authorization: ["Authorized to work", "Needs sponsorship", "EU/EFTA eligible", "Swiss permit", "Student permit", "Not sure"],
  swiss_permit_status: ["B permit", "C permit", "L permit", "G permit", "Ci permit", "S permit", "Other / in progress"],
};

const preferenceSuggestions: Record<PreferenceListField, string[]> = {
  desired_roles: [
    "Python Developer",
    "Backend Developer",
    "AI Engineer",
    "Full-stack Developer",
    "Data Engineer",
    "Machine Learning Engineer",
  ],
  locations: ["Switzerland", "Zurich", "Remote Europe", "Germany", "Austria", "Netherlands", "Remote worldwide"],
  industries: ["AI", "SaaS", "FinTech", "HealthTech", "Developer tools", "EdTech", "E-commerce", "Cybersecurity"],
  languages: ["English C1", "English B2", "German A2", "German B1", "French B1", "Russian native"],
};

const suggestedDealbreakers = [
  "No onsite-only roles",
  "Remote or hybrid only",
  "Minimum salary CHF 100,000",
  "No contract roles",
  "Full-time only",
  "No relocation outside Switzerland",
  "No unpaid internships",
  "No roles requiring fluent German",
  "No crypto or gambling industry",
  "Must support Swiss permit",
];

const preferenceListLabels: Record<PreferenceListField, { label: string; placeholder: string }> = {
  desired_roles: { label: "Desired roles", placeholder: "Python Developer, AI Engineer..." },
  locations: { label: "Locations", placeholder: "Zurich, Switzerland, Remote Europe..." },
  industries: { label: "Industries", placeholder: "AI, SaaS, FinTech..." },
  languages: { label: "Languages", placeholder: "English C1, German A2..." },
};

const preferenceSummaryLabels: Record<PreferenceAnyField, string> = {
  desired_roles: "Roles",
  seniority: "Seniority",
  locations: "Locations",
  work_formats: "Work format",
  employment_types: "Employment",
  industries: "Industries",
  salary: "Salary floor",
  work_authorization: "Authorization",
  languages: "Languages",
  company_sizes: "Company size",
  priorities: "Priorities",
};

const suggestedSkills = [
  "Agile Development",
  "AI Agent Development",
  "AI Application Development",
  "AI Engineering",
  "AI Integrations",
  "AI Literacy",
  "AI Model Evaluation",
  "AI Safety",
  "AI Strategy",
  "AJAX",
  "API Design",
  "API Development",
  "API Integration",
  "ASP.NET",
  "AWS",
  "AWS Lambda",
  "Accessibility",
  "Algorithms",
  "Angular",
  "Ansible",
  "Apache Kafka",
  "Application Security",
  "Architecture",
  "AsyncIO",
  "Authentication",
  "Automation",
  "Azure",
  "Bash",
  "Bootstrap",
  "CI/CD",
  "CSS",
  "Celery",
  "Chatbot Development",
  "Clean Architecture",
  "Clean Code",
  "Cloud Applications",
  "Cloud Computing",
  "Cloud Functions",
  "Cloud Security",
  "Code Review",
  "Computer Vision",
  "Continuous Deployment",
  "Continuous Integration",
  "Critical Thinking",
  "Cybersecurity",
  "Django",
  "Django REST Framework",
  "Docker",
  "Docker Compose",
  "Domain-Driven Design",
  "Elasticsearch",
  "Express.js",
  "FastAPI",
  "Firebase",
  "Flask",
  "Frontend Development",
  "Full-stack Development",
  "GCP",
  "Git",
  "GitHub",
  "GitHub Actions",
  "GitLab CI",
  "Go",
  "GraphQL",
  "HTML",
  "Helm",
  "Hugging Face",
  "Java",
  "JavaScript",
  "Jenkins",
  "Jest",
  "Jira",
  "Jupyter",
  "JWT",
  "Kubernetes",
  "LangChain",
  "LangGraph",
  "Large Language Models",
  "Linux",
  "LLM Applications",
  "LLM Evaluation",
  "Machine Learning",
  "Microservices",
  "MongoDB",
  "MySQL",
  "Next.js",
  "Nginx",
  "Node.js",
  "NoSQL",
  "OAuth",
  "Object-Oriented Programming",
  "OpenAPI",
  "PHP",
  "Pandas",
  "Performance Optimization",
  "Playwright",
  "PostgreSQL",
  "Postman",
  "Problem Solving",
  "Prompt Engineering",
  "PyTorch",
  "Pytest",
  "Python",
  "QA Automation",
  "RabbitMQ",
  "React",
  "React Native",
  "Redis",
  "Refactoring",
  "Relational Databases",
  "REST API",
  "Ruby",
  "Ruby on Rails",
  "Rust",
  "SaaS Development",
  "Scikit-learn",
  "Scrum",
  "Security Best Practices",
  "Serverless",
  "Shell Scripting",
  "Software Architecture",
  "Software Design",
  "Software Development",
  "Software Engineering",
  "Software Testing",
  "Spring Boot",
  "SQL",
  "SQLite",
  "System Design",
  "Tailwind CSS",
  "Team Collaboration",
  "TensorFlow",
  "Terraform",
  "Test Automation",
  "Test-Driven Development",
  "TypeScript",
  "UI Development",
  "Unit Testing",
  "Unix",
  "UX Basics",
  "Vector Databases",
  "Vercel",
  "Vue.js",
  "Web APIs",
  "Web Development",
  "WebSockets",
  "Webpack",
  "WordPress",
  "XML",
  "YAML",
  "Zod",
  "NumPy",
  "Data Analysis",
  "Data Engineering",
  "Data Structures",
  "Data Visualization",
  "ETL",
  "MLOps",
  "MLflow",
  "RAG",
  "Retrieval-Augmented Generation",
  "Pinecone",
  "ChromaDB",
  "Qdrant",
  "Supabase",
  "Prisma",
  "SQLAlchemy",
  "ORM",
  "Pydantic",
  "Redux",
  "Zustand",
  "Svelte",
  "Nuxt.js",
  "Vite",
  "ESLint",
  "Prettier",
  "Cypress",
  "Mocha",
  "Vitest",
  "Storybook",
  "Figma",
  "Responsive Design",
  "Mobile Development",
  "Swift",
  "Kotlin",
  "Flutter",
  "Dart",
  "C",
  "C++",
  "C#",
  ".NET",
  "Graph Databases",
  "Neo4j",
  "Observability",
  "Monitoring",
  "Logging",
  "Prometheus",
  "Grafana",
  "Sentry",
  "Datadog",
  "DevOps",
  "Site Reliability Engineering",
  "Backend Development",
  "Infrastructure as Code",
  "Networking",
  "HTTP",
  "DNS",
  "TCP/IP",
  "Web Security",
  "OWASP",
  "Encryption",
  "OAuth 2.0",
  "SAML",
  "JSON",
  "gRPC",
  "Message Queues",
  "Event-Driven Architecture",
  "Distributed Systems",
  "Concurrency",
  "Multithreading",
  "Design Patterns",
  "Technical Documentation",
  "Debugging",
  "Troubleshooting",
  "Production Support",
  "Product Thinking",
  "Cross-functional Collaboration",
  "Communication",
  "Adaptability",
  "Agile Problem Solving",
];

const legacyCandidateProfileValues: Partial<CandidateProfile> = {
  name: "Alex Johnson",
  current_role: "Senior Product Designer",
  desired_role: "Design Manager",
  location: "San Francisco, CA, USA",
  work_format: "Remote, open to hybrid",
  headline:
    "Product designer with 7+ years of experience crafting intuitive B2B and B2C digital experiences. Combines user empathy with data-driven design to ship impactful products.",
  linkedin: "linkedin.com/in/alexjohnson",
  github: "github.com/alexjohnson",
  portfolio: "alexjohnson.design",
  personal_site: "alexjohnson.com",
};

function normalizeCandidateProfile(profile: Partial<CandidateProfile>): CandidateProfile {
  const normalizedProfile = { ...defaultCandidateProfile, ...profile };

  if (!normalizedProfile.avatar_url || normalizedProfile.avatar_url === "/avatars/pug.svg") {
    normalizedProfile.avatar_url = defaultCandidateProfile.avatar_url;
  }

  for (const [field, legacyValue] of Object.entries(legacyCandidateProfileValues) as Array<[keyof CandidateProfile, string]>) {
    if (normalizedProfile[field] === legacyValue) {
      normalizedProfile[field] = "";
    }
  }

  return normalizedProfile;
}

function hasProfileValue(value: string | undefined) {
  return Boolean(value?.trim());
}

function hasCandidateProfileData(profile: CandidateProfile) {
  return candidateProfileDataFields.some((field) => hasProfileValue(profile[field]));
}

function readStoredCandidateProfile() {
  try {
    const rawProfile = window.localStorage.getItem(profileStorageKey);
    if (!rawProfile) return null;

    const storedProfile = normalizeCandidateProfile(JSON.parse(rawProfile) as Partial<CandidateProfile>);
    return hasCandidateProfileData(storedProfile) ? storedProfile : null;
  } catch {
    window.localStorage.removeItem(profileStorageKey);
    return null;
  }
}

function cacheCandidateProfile(profile: CandidateProfile) {
  if (hasCandidateProfileData(profile)) {
    window.localStorage.setItem(profileStorageKey, JSON.stringify(profile));
  } else {
    window.localStorage.removeItem(profileStorageKey);
  }
}

function displayProfileValue(value: string, fallback: string) {
  return hasProfileValue(value) ? value : fallback;
}

function displayProfileFirstName(value: string, fallback: string) {
  return hasProfileValue(value) ? value.trim().split(/\s+/)[0] : fallback;
}

function normalizeExternalUrl(value: string) {
  const trimmedValue = value.trim();

  if (!trimmedValue) return "";
  if (/^https?:\/\//i.test(trimmedValue)) return trimmedValue;
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedValue)) return `mailto:${trimmedValue}`;
  if (/^[a-z][a-z\d+\-.]*:/i.test(trimmedValue)) return "";

  return `https://${trimmedValue.replace(/^\/+/, "")}`;
}

function parseProfileLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeExperienceEntry(entry: Partial<ExperienceEntry>): ExperienceEntry {
  return {
    ...defaultExperienceDraft,
    ...entry,
    id: entry.id || createClientId("experience"),
    title: entry.title?.trim() ?? "",
    company: entry.company?.trim() ?? "",
    employment_type: entry.employment_type?.trim() || "Full-time",
    location: entry.location?.trim() ?? "",
    start_date: entry.start_date?.trim() ?? "",
    end_date: entry.is_current ? "" : entry.end_date?.trim() ?? "",
    is_current: Boolean(entry.is_current),
    description: entry.description?.trim() ?? "",
  };
}

function parseExperienceEntries(value: string): ExperienceEntry[] {
  if (!value.trim()) return [];

  try {
    const parsed = JSON.parse(value) as unknown;
    if (Array.isArray(parsed)) {
      return parsed
        .filter((item): item is Partial<ExperienceEntry> => Boolean(item) && typeof item === "object")
        .map((item) => normalizeExperienceEntry(item))
        .filter((item) => item.title || item.company || item.description);
    }
  } catch {
    // Fall back to the previous one-line-per-entry format.
  }

  return parseProfileLines(value).map((item, index) =>
    normalizeExperienceEntry({
      id: `legacy-experience-${index}`,
      title: item,
      description: item,
    }),
  );
}

function serializeExperienceEntries(entries: ExperienceEntry[]) {
  return JSON.stringify(entries.map((entry) => normalizeExperienceEntry(entry)));
}

function getExperienceFingerprint(entry: ExperienceEntry) {
  return [entry.title, entry.company, entry.start_date, entry.end_date]
    .map((value) => value.trim().toLowerCase())
    .join("|");
}

function mergeExperienceEntries(currentEntries: ExperienceEntry[], importedEntries: ExperienceEntry[]) {
  const existingFingerprints = new Set(currentEntries.map(getExperienceFingerprint));
  const nextEntries = [...currentEntries];

  for (const entry of importedEntries) {
    const fingerprint = getExperienceFingerprint(entry);
    if (!entry.title || !entry.company || existingFingerprints.has(fingerprint)) {
      continue;
    }

    existingFingerprints.add(fingerprint);
    nextEntries.push(entry);
  }

  return nextEntries;
}

function normalizeEducationEntry(entry: Partial<EducationEntry>): EducationEntry {
  return {
    ...defaultEducationDraft,
    ...entry,
    id: entry.id || createClientId("education"),
    institution: entry.institution?.trim() ?? "",
    credential: entry.credential?.trim() ?? "",
    field_of_study: entry.field_of_study?.trim() ?? "",
    location: entry.location?.trim() ?? "",
    start_date: entry.start_date?.trim() ?? "",
    end_date: entry.is_current ? "" : entry.end_date?.trim() ?? "",
    is_current: Boolean(entry.is_current),
    description: entry.description?.trim() ?? "",
  };
}

function parseEducationEntries(value: string): EducationEntry[] {
  if (!value.trim()) return [];

  try {
    const parsed = JSON.parse(value) as unknown;
    if (Array.isArray(parsed)) {
      return parsed
        .filter((item): item is Partial<EducationEntry> => Boolean(item) && typeof item === "object")
        .map((item) => normalizeEducationEntry(item))
        .filter((item) => item.institution || item.credential || item.field_of_study || item.description);
    }
  } catch {
    // Fall back to the previous one-line-per-entry format.
  }

  return parseProfileLines(value).map((item, index) =>
    normalizeEducationEntry({
      id: `legacy-education-${index}`,
      credential: item,
      description: item,
    }),
  );
}

function serializeEducationEntries(entries: EducationEntry[]) {
  return JSON.stringify(entries.map((entry) => normalizeEducationEntry(entry)));
}

function getEducationFingerprint(entry: EducationEntry) {
  return [entry.institution, entry.credential, entry.field_of_study, entry.start_date, entry.end_date]
    .map((value) => value.trim().toLowerCase())
    .join("|");
}

function mergeEducationEntries(currentEntries: EducationEntry[], importedEntries: EducationEntry[]) {
  const existingFingerprints = new Set(currentEntries.map(getEducationFingerprint));
  const nextEntries = [...currentEntries];

  for (const entry of importedEntries) {
    const fingerprint = getEducationFingerprint(entry);
    if ((!entry.institution && !entry.credential) || existingFingerprints.has(fingerprint)) {
      continue;
    }

    existingFingerprints.add(fingerprint);
    nextEntries.push(entry);
  }

  return nextEntries;
}

function normalizeDocumentEntry(
  entry: Partial<DocumentEntry>,
  fallbackId = "",
): DocumentEntry {
  return {
    ...defaultDocumentDraft,
    ...entry,
    id: entry.id || fallbackId || createClientId("document"),
    title: entry.title?.trim() ?? "",
    category: entry.category?.trim() || "Other",
    language: entry.language?.trim() || inferDocumentLanguage(entry.file_name ?? "", entry.title ?? ""),
    issuer: entry.issuer?.trim() ?? "",
    notes: entry.notes?.trim() ?? "",
    file_name: entry.file_name?.trim() ?? "",
    file_size: entry.file_size?.trim() ?? "",
    file_type: entry.file_type?.trim() ?? "",
    uploaded_at: entry.uploaded_at?.trim() ?? "",
    data_url: entry.data_url ?? "",
  };
}

function inferDocumentLanguage(fileName: string, title = "") {
  const value = `${fileName} ${title}`.toLowerCase();
  if (/(?:^|[\s_.-])(de|deu|ger)(?:[\s_.-]|$)|deutsch|german/.test(value)) return "German";
  if (/(?:^|[\s_.-])(en|eng)(?:[\s_.-]|$)|english/.test(value)) return "English";
  return "";
}

function parseDocumentEntries(value: string): DocumentEntry[] {
  if (!value.trim()) return [];

  try {
    const parsed = JSON.parse(value) as unknown;
    if (Array.isArray(parsed)) {
      return parsed
        .filter((item): item is Partial<DocumentEntry> => Boolean(item) && typeof item === "object")
        // Older profiles may contain documents without IDs. The fallback must
        // be deterministic: parsing once for render and again for delete/edit
        // must address the same item. The next successful save persists it.
        .map((item, index) => normalizeDocumentEntry(item, `legacy-document-${index}`))
        .filter((item) => item.title || item.file_name || item.data_url);
    }
  } catch {
    return [];
  }

  return [];
}

function serializeDocumentEntries(entries: DocumentEntry[]) {
  if (entries.length === 0) return "";

  return JSON.stringify(entries.map((entry) => normalizeDocumentEntry(entry)));
}

function normalizePreferenceList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];

  return Array.from(
    new Map(
      value
        .filter((item): item is string => typeof item === "string")
        .map((item) => item.trim())
        .filter(Boolean)
        .map((item) => [item.toLowerCase(), item]),
    ).values(),
  );
}

function normalizeNoPreferenceFields(value: unknown): PreferenceAnyField[] {
  const allowedFields = new Set<PreferenceAnyField>([
    "desired_roles",
    "seniority",
    "locations",
    "work_formats",
    "employment_types",
    "industries",
    "salary",
    "work_authorization",
    "languages",
    "company_sizes",
    "priorities",
  ]);

  return normalizePreferenceList(value).filter((item): item is PreferenceAnyField =>
    allowedFields.has(item as PreferenceAnyField),
  );
}

function normalizeJobPreferences(value: Partial<JobPreferences>): JobPreferences {
  return {
    ...defaultJobPreferences,
    ...value,
    desired_roles: normalizePreferenceList(value.desired_roles),
    seniority: normalizePreferenceList(value.seniority),
    locations: normalizePreferenceList(value.locations),
    work_formats: normalizePreferenceList(value.work_formats),
    employment_types: normalizePreferenceList(value.employment_types),
    industries: normalizePreferenceList(value.industries),
    salary_min: value.salary_min?.trim() ?? "",
    salary_currency: value.salary_currency?.trim() || "CHF",
    work_authorization: value.work_authorization?.trim() ?? "",
    swiss_permit_status: value.work_authorization?.trim() === "Swiss permit"
      ? value.swiss_permit_status?.trim() ?? ""
      : "",
    languages: normalizePreferenceList(value.languages),
    company_sizes: normalizePreferenceList(value.company_sizes),
    priorities: normalizePreferenceList(value.priorities),
    notes: value.notes?.trim() ?? "",
    no_preference: normalizeNoPreferenceFields(value.no_preference),
  };
}

function parseJobPreferences(value: string): JobPreferences {
  if (!value.trim()) return defaultJobPreferences;

  try {
    const parsed = JSON.parse(value) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return normalizeJobPreferences(parsed as Partial<JobPreferences>);
    }
  } catch {
    // Fall back to the previous one-line-per-preference format.
  }

  return normalizeJobPreferences({ notes: parseProfileLines(value).join("\n") });
}

function serializeJobPreferences(preferences: JobPreferences) {
  const normalizedPreferences = normalizeJobPreferences(preferences);
  const hasValues =
    normalizedPreferences.desired_roles.length > 0 ||
    normalizedPreferences.seniority.length > 0 ||
    normalizedPreferences.locations.length > 0 ||
    normalizedPreferences.work_formats.length > 0 ||
    normalizedPreferences.employment_types.length > 0 ||
    normalizedPreferences.industries.length > 0 ||
    hasProfileValue(normalizedPreferences.salary_min) ||
    hasProfileValue(normalizedPreferences.work_authorization) ||
    hasProfileValue(normalizedPreferences.swiss_permit_status) ||
    normalizedPreferences.languages.length > 0 ||
    normalizedPreferences.company_sizes.length > 0 ||
    normalizedPreferences.priorities.length > 0 ||
    normalizedPreferences.no_preference.length > 0 ||
    hasProfileValue(normalizedPreferences.notes);

  return hasValues ? JSON.stringify(normalizedPreferences) : "";
}

function formatPreferenceSummary(preferences: JobPreferences) {
  const preferenceValue = (field: PreferenceAnyField, values: string[]) =>
    preferences.no_preference.includes(field) ? ["No preference"] : values;

  const items: Array<{ label: string; values: string[] }> = [
    { label: "Roles", values: preferenceValue("desired_roles", preferences.desired_roles) },
    { label: "Seniority", values: preferenceValue("seniority", preferences.seniority) },
    { label: "Locations", values: preferenceValue("locations", preferences.locations) },
    { label: "Work format", values: preferenceValue("work_formats", preferences.work_formats) },
    { label: "Employment", values: preferenceValue("employment_types", preferences.employment_types) },
    { label: "Industries", values: preferenceValue("industries", preferences.industries) },
    { label: "Languages", values: preferenceValue("languages", preferences.languages) },
    { label: "Company size", values: preferenceValue("company_sizes", preferences.company_sizes) },
    { label: "Priorities", values: preferenceValue("priorities", preferences.priorities) },
  ].filter((item) => item.values.length > 0);

  if (preferences.no_preference.includes("salary")) {
    items.splice(6, 0, { label: "Salary floor", values: ["No preference"] });
  } else if (hasProfileValue(preferences.salary_min)) {
    items.splice(6, 0, { label: "Salary floor", values: [`${preferences.salary_currency} ${preferences.salary_min}`] });
  }

  if (preferences.no_preference.includes("work_authorization")) {
    items.splice(7, 0, { label: "Authorization", values: ["No preference"] });
  } else if (hasProfileValue(preferences.work_authorization)) {
    const authorizationValues = preferences.work_authorization === "Swiss permit" && hasProfileValue(preferences.swiss_permit_status)
      ? [`${preferences.work_authorization} (${preferences.swiss_permit_status})`]
      : [preferences.work_authorization];
    items.splice(7, 0, { label: "Authorization", values: authorizationValues });
  }

  if (hasProfileValue(preferences.notes)) {
    items.push({ label: "Notes", values: [preferences.notes] });
  }

  return items;
}

function hasQuantifiedAchievements(entries: ExperienceEntry[]) {
  return entries.some((entry) => /\d|%|\bpercent\b|\busers?\b|\bclients?\b|\brevenue\b|\bcost\b|\bsaved\b|\breduced\b|\bincreased\b/i.test(entry.description));
}

function formatCompactList(values: string[], fallback: string) {
  if (values.length === 0) return fallback;
  if (values.length <= 3) return values.join(", ");
  return `${values.slice(0, 3).join(", ")} +${values.length - 3} more`;
}

function getAiMatchProfile(profile: CandidateProfile) {
  const skills = parseProfileLines(profile.skills);
  const experienceEntries = parseExperienceEntries(profile.experience);
  const educationEntries = parseEducationEntries(profile.education);
  const preferences = parseJobPreferences(profile.job_preferences);
  const hasResume = hasProfileValue(profile.resume_file_name) && hasProfileValue(profile.resume_data_url);
  const hasSalaryPreference = preferences.no_preference.includes("salary") || hasProfileValue(preferences.salary_min);
  const hasAuthorizationPreference = preferences.no_preference.includes("work_authorization") || hasProfileValue(preferences.work_authorization);
  const hasLocationPreference = preferences.no_preference.includes("locations") || preferences.locations.length > 0;
  const hasIndustryPreference = preferences.no_preference.includes("industries") || preferences.industries.length > 0;
  const hasRolePreference = preferences.no_preference.includes("desired_roles") || preferences.desired_roles.length > 0 || hasProfileValue(profile.desired_role);

  const signals = [
    hasProfileValue(profile.current_role) ? `Current role: ${profile.current_role}` : "",
    hasProfileValue(profile.desired_role) ? `Target: ${profile.desired_role}` : "",
    skills.length > 0 ? `${skills.length} skills: ${formatCompactList(skills, "skills added")}` : "",
    experienceEntries.length > 0 ? `${experienceEntries.length} experience entr${experienceEntries.length === 1 ? "y" : "ies"}` : "",
    educationEntries.length > 0 ? `${educationEntries.length} education / certification entr${educationEntries.length === 1 ? "y" : "ies"}` : "",
    hasLocationPreference ? `Locations: ${preferences.no_preference.includes("locations") ? "No preference" : formatCompactList(preferences.locations, "set")}` : "",
    hasAuthorizationPreference ? `Work authorization: ${preferences.no_preference.includes("work_authorization") ? "No preference" : preferences.work_authorization}` : "",
    hasResume ? `Resume attached: ${profile.resume_file_name}` : "",
  ].filter(Boolean);

  const gaps = [
    !hasProfileValue(profile.current_role) ? "Add current role" : "",
    !hasRolePreference ? "Add target role or desired roles" : "",
    skills.length === 0 ? "Add skills" : "",
    experienceEntries.length === 0 ? "Add or import work experience" : "",
    experienceEntries.length > 0 && !hasQuantifiedAchievements(experienceEntries) ? "Add quantified achievements to experience" : "",
    !hasLocationPreference ? "Add preferred locations or mark no preference" : "",
    !hasIndustryPreference ? "Add preferred industries or mark no preference" : "",
    !hasSalaryPreference ? "Add salary preference or mark no preference" : "",
    !hasAuthorizationPreference ? "Add work authorization preference or mark no preference" : "",
    !hasResume ? "Attach resume for imports and matching" : "",
  ].filter(Boolean);

  return {
    signals,
    gaps: gaps.slice(0, 5),
  };
}

function formatFileSize(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatProfileDate(value: string) {
  if (!value) return "";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function getProfileCompletionItems(profile: CandidateProfile) {
  const skills = parseProfileLines(profile.skills);
  const experienceEntries = parseExperienceEntries(profile.experience);
  const educationEntries = parseEducationEntries(profile.education);
  const preferences = parseJobPreferences(profile.job_preferences);
  const hasRolePreference = preferences.no_preference.includes("desired_roles") || preferences.desired_roles.length > 0 || hasProfileValue(profile.desired_role);
  const hasLocationPreference = preferences.no_preference.includes("locations") || preferences.locations.length > 0 || hasProfileValue(profile.location);
  const hasAuthorizationPreference = preferences.no_preference.includes("work_authorization") || hasProfileValue(preferences.work_authorization);
  const hasSalaryPreference = preferences.no_preference.includes("salary") || hasProfileValue(preferences.salary_min);

  return [
    {
      label: "Name and current role",
      complete: hasProfileValue(profile.name) && hasProfileValue(profile.current_role),
      action: "Add name and current role",
    },
    {
      label: "Target role",
      complete: hasRolePreference,
      action: "Add target role or desired roles",
    },
    {
      label: "Location and work format",
      complete: hasProfileValue(profile.location) && hasProfileValue(profile.work_format),
      action: "Add location and work format",
    },
    {
      label: "Summary",
      complete: hasProfileValue(profile.headline),
      action: "Add short professional summary",
    },
    {
      label: "Contact link",
      complete: getProfileLinks(profile).some((link) => hasProfileValue(link.value) && link.href),
      action: "Add LinkedIn, GitHub, or portfolio",
    },
    {
      label: "Resume",
      complete: hasProfileValue(profile.resume_file_name) && hasProfileValue(profile.resume_data_url),
      action: "Attach resume",
    },
    {
      label: "Experience",
      complete: experienceEntries.length > 0,
      action: "Add or import experience",
    },
    {
      label: "Quantified achievements",
      complete: experienceEntries.length > 0 && hasQuantifiedAchievements(experienceEntries),
      action: "Add metrics to experience",
    },
    {
      label: "Skills",
      complete: skills.length >= 6,
      action: skills.length > 0 ? "Add a few more skills" : "Add skills",
    },
    {
      label: "Education or certification",
      complete: educationEntries.length > 0,
      action: "Add education or certification",
    },
    {
      label: "Preferred locations",
      complete: hasLocationPreference,
      action: "Add preferred locations or mark no preference",
    },
    {
      label: "Work authorization",
      complete: hasAuthorizationPreference,
      action: "Add work authorization preference",
    },
    {
      label: "Salary preference",
      complete: hasSalaryPreference,
      action: "Add salary floor or mark no preference",
    },
  ];
}

function getProfileCompletion(profile: CandidateProfile) {
  const completionItems = getProfileCompletionItems(profile);
  const completedFields = completionItems.filter((item) => item.complete);

  return Math.round((completedFields.length / completionItems.length) * 100);
}

function getParserLabel(parser: string | undefined) {
  if (parser === "indeed") return "Indeed";
  if (parser === "jobs_ch" || parser === "jobs.ch") return "jobs.ch";
  return "LinkedIn";
}

function getParsersLabel(parsers: ParserId[]) {
  return parsers.map(getParserLabel).join(" + ");
}

function normalizeParserIds(form: ParserSearchForm): ParserId[] {
  const parserCandidates = Array.isArray(form.parsers) ? form.parsers : [];
  const legacyParser = (form as ParserSearchForm & { parser?: unknown }).parser;
  const validParsers = parserCandidates.filter(
    (parser): parser is ParserId =>
      parser === "linkedin" || parser === "indeed" || parser === "jobs_ch",
  );
  if (validParsers.length > 0) return Array.from(new Set(validParsers));
  if (legacyParser === "linkedin" || legacyParser === "indeed" || legacyParser === "jobs_ch") {
    return [legacyParser];
  }
  return [...defaultParserSearchForm.parsers];
}

const manualJobSkillPatterns: Array<{ label: string; pattern: RegExp }> = [
  { label: "IPX", pattern: /\bipx\b/i },
  { label: "HVAC", pattern: /\bhvac\b/i },
  { label: "IoT", pattern: /\biot\b/i },
  { label: "Embedded systems", pattern: /\bembedded\b/i },
  { label: "Firmware", pattern: /\bfirmware\b/i },
  { label: "IP networking", pattern: /\bip\s+(network|networking|protocol)|\bnetworking\b/i },
  { label: "Cybersecurity", pattern: /\bcyber\s?security|security\b/i },
  { label: "Cloud", pattern: /\bcloud\b/i },
  { label: "AWS", pattern: /\baws\b/i },
  { label: "Azure", pattern: /\bazure\b/i },
  { label: "GCP", pattern: /\bgcp|google cloud\b/i },
  { label: "Python", pattern: /\bpython\b/i },
  { label: "JavaScript", pattern: /\bjavascript|js\b/i },
  { label: "TypeScript", pattern: /\btypescript|ts\b/i },
  { label: "React", pattern: /\breact\b/i },
  { label: "Node.js", pattern: /\bnode(?:\.js)?\b/i },
  { label: "Java", pattern: /\bjava\b/i },
  { label: "C++", pattern: /\bc\+\+\b/i },
  { label: "C#", pattern: /\bc#\b/i },
  { label: "SQL", pattern: /\bsql\b/i },
  { label: "Data analysis", pattern: /\bdata analysis|analytics|analyse|analysis\b/i },
  { label: "Machine learning", pattern: /\bmachine learning|ml\b/i },
  { label: "AI", pattern: /\bartificial intelligence|\bai\b/i },
  { label: "Figma", pattern: /\bfigma\b/i },
  { label: "UX", pattern: /\bux|user experience\b/i },
  { label: "UI", pattern: /\bui|user interface\b/i },
  { label: "Product management", pattern: /\bproduct management|product owner\b/i },
  { label: "Project management", pattern: /\bproject management|coordination|coordinate\b/i },
  { label: "Agile", pattern: /\bagile|scrum|kanban\b/i },
  { label: "SAP", pattern: /\bsap\b/i },
  { label: "Excel", pattern: /\bexcel\b/i },
  { label: "Power BI", pattern: /\bpower\s?bi\b/i },
  { label: "Communication", pattern: /\bcommunication|stakeholder|presentation\b/i },
  { label: "English", pattern: /\benglish\b/i },
  { label: "German", pattern: /\bgerman|deutsch\b/i },
  { label: "French", pattern: /\bfrench|franzosisch|francais\b/i },
];

function splitJobDescriptionItems(value: string) {
  return value
    .replace(/\r/g, "")
    .split(/\n+|[.;]\s+/)
    .map((item) => item.replace(/^[-*•\d.)\s]+/, "").trim())
    .filter((item) => item.length >= 8);
}

function truncateJobText(value: string, maxLength = 180) {
  const normalizedValue = value.replace(/\s+/g, " ").trim();
  if (normalizedValue.length <= maxLength) return normalizedValue;
  return `${normalizedValue.slice(0, maxLength - 1).trim()}...`;
}

function uniqueJobItems(items: string[], limit: number) {
  return Array.from(
    new Map(
      items
        .map((item) => truncateJobText(item))
        .filter(Boolean)
        .map((item) => [item.toLowerCase(), item]),
    ).values(),
  ).slice(0, limit);
}

function inferManualJobType(text: string) {
  if (/\bworking student\b/i.test(text)) return "Working student";
  if (/\bintern(ship)?|trainee\b/i.test(text)) return "Internship";
  if (/\bfreelance|self-employed\b/i.test(text)) return "Freelance";
  if (/\bcontract|temporary|befristet\b/i.test(text)) return "Contract";
  if (/\bpart[-\s]?time|\b[2-8]0\s?%/i.test(text)) return "Part-time";
  if (/\bfull[-\s]?time|100\s?%/i.test(text)) return "Full-time";
  return "Not specified";
}

function inferManualJobExperience(text: string) {
  if (/\bworking student\b|\bintern(ship)?|trainee|student|entry[-\s]?level|junior|graduate\b/i.test(text)) return "Entry level";
  if (/\bassociate\b/i.test(text)) return "Associate";
  if (/\bsenior|sr\.?|lead|principal|staff|head of|director\b/i.test(text)) return "Senior";
  if (/\bmid[-\s]?level|professional|experienced\b/i.test(text)) return "Mid-level";

  const years = text.match(/\b(\d+)\+?\s*(?:years?|yrs?)\b/i)?.[1];
  if (!years) return "Not specified";

  const yearCount = Number.parseInt(years, 10);
  if (yearCount >= 5) return `${yearCount}+ years`;
  if (yearCount >= 2) return `${yearCount}+ years`;
  return "Entry level";
}

function inferManualJobSalary(text: string) {
  const salaryMatch = text.match(
    /(?:CHF|EUR|USD|GBP|[$€£])\s?[\d'.,]+(?:\s?[kK])?(?:\s?[-–]\s?(?:CHF|EUR|USD|GBP|[$€£])?\s?[\d'.,]+(?:\s?[kK])?)?/,
  );
  return salaryMatch?.[0].replace(/\s+/g, " ").trim() || "Not specified";
}

function inferManualJobDepartment(text: string) {
  const departmentPatterns: Array<{ label: string; pattern: RegExp }> = [
    { label: "Product", pattern: /\bproduct\b/i },
    { label: "Design", pattern: /\bdesign|ux|ui\b/i },
    { label: "Engineering", pattern: /\bengineering|software|developer|embedded|firmware\b/i },
    { label: "IT", pattern: /\bit\b|information technology|network|cyber/i },
    { label: "Data", pattern: /\bdata|analytics|machine learning|ai\b/i },
    { label: "Marketing", pattern: /\bmarketing|brand|campaign\b/i },
    { label: "Sales", pattern: /\bsales|business development|account\b/i },
    { label: "Operations", pattern: /\boperations|supply chain|logistics\b/i },
    { label: "Finance", pattern: /\bfinance|accounting|controlling\b/i },
    { label: "People", pattern: /\bhr|people|talent|recruiting\b/i },
    { label: "Manufacturing", pattern: /\bmanufacturing|production|quality\b/i },
  ];
  const departments = departmentPatterns
    .filter((item) => item.pattern.test(text))
    .map((item) => item.label);

  return departments.length > 0 ? departments.slice(0, 2).join(" / ") : "Manual entry";
}

function extractManualJobSkills(text: string) {
  const matchedSkills = manualJobSkillPatterns
    .filter((item) => item.pattern.test(text))
    .map((item) => item.label);

  return uniqueJobItems(matchedSkills, 14);
}

function extractManualJobRequirements(description: string, title: string) {
  const items = splitJobDescriptionItems(description);
  const requirementItems = items.filter((item) =>
    /\brequire|qualification|profile|experience|knowledge|skill|degree|student|fluent|english|german|must|you have|you bring|familiar|proficient|able to\b/i.test(item),
  );

  return uniqueJobItems(requirementItems, 6).length > 0
    ? uniqueJobItems(requirementItems, 6)
    : uniqueJobItems([`Relevant background for ${title}`, "Review the vacancy description before applying"], 2);
}

function extractManualJobResponsibilities(description: string) {
  const items = splitJobDescriptionItems(description);
  const responsibilityItems = items.filter((item) =>
    /\bresponsib|support|develop|create|design|analy[sz]e|manage|maintain|coordinate|collaborate|contribute|work with|implement|build|prepare\b/i.test(item),
  );

  return uniqueJobItems(responsibilityItems, 6).length > 0
    ? uniqueJobItems(responsibilityItems, 6)
    : ["Track application progress", "Keep next steps and events up to date"];
}

function analyzeManualJobDescription(draft: ManualJobDraft) {
  const title = draft.title.trim();
  const description = draft.overview.trim();
  const analysisText = [title, draft.company, draft.location, description].filter(Boolean).join("\n");
  const skills = extractManualJobSkills(analysisText);

  return {
    type: inferManualJobType(analysisText),
    salary: inferManualJobSalary(analysisText),
    experience: inferManualJobExperience(analysisText),
    department: inferManualJobDepartment(analysisText),
    responsibilities: extractManualJobResponsibilities(description),
    requirements: extractManualJobRequirements(description, title),
    skills: skills.length > 0 ? skills : ["Manual entry"],
  };
}

function createManualJobFromDraft(draft: ManualJobDraft): Job {
  const title = draft.title.trim();
  const company = draft.company.trim();
  const location = draft.location.trim() || "Not specified";
  const applyUrl = normalizeExternalUrl(draft.applyUrl);
  const analysis = analyzeManualJobDescription(draft);

  return {
    id: createClientId("manual-job"),
    company,
    title,
    location,
    type: analysis.type,
    salary: analysis.salary,
    posted: "Manual entry",
    experience: analysis.experience,
    department: analysis.department,
    match: 50,
    logo: "manual",
    overview: draft.overview.trim() || "Manually added vacancy. Add notes, events, and next steps from the application tracker.",
    responsibilities: analysis.responsibilities,
    requirements: analysis.requirements,
    skills: analysis.skills,
    salaryAverage: "N/A",
    salaryMin: "N/A",
    salaryMax: "N/A",
    recommendations: [],
    companyInfo: `${company} vacancy added manually${applyUrl ? `: ${applyUrl}` : "."}`,
    reviews: ["This vacancy was added manually and has not been scored yet."],
    similarJobs: [],
    applyUrl: applyUrl || undefined,
    sourceUrl: applyUrl || undefined,
    addedAt: new Date().toISOString(),
  };
}

function wait(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function readApiErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    return formatApiErrorDetail(payload.detail) || formatApiErrorDetail(payload.message) || fallback;
  } catch {
    // Error responses are not guaranteed to be JSON.
  }

  return fallback;
}

function formatApiErrorDetail(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value.map(formatApiErrorDetail).filter(Boolean).join("; ");
  }
  if (!value || typeof value !== "object") return "";

  const detail = value as Record<string, unknown>;
  if (typeof detail.msg === "string" && detail.msg.trim()) {
    const location = Array.isArray(detail.loc)
      ? detail.loc.filter((part) => part !== "body").map(String).join(".")
      : "";
    return location ? `${location}: ${detail.msg.trim()}` : detail.msg.trim();
  }

  return formatApiErrorDetail(detail.detail) || formatApiErrorDetail(detail.message);
}

function createClientId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeParserSearchConfigs(configs: ParserSearchConfig[]) {
  const normalizedConfigs = configs
    .filter((config) => config.id && config.name && config.form)
    .map((config) => ({
      ...config,
      form: {
        ...defaultParserSearchForm,
        ...config.form,
        parsers: normalizeParserIds(config.form),
      },
      filters: isRecord(config.filters)
        ? config.filters
        : parserSearchFiltersFromForm(config.form),
    }));
  const uniqueConfigs = new Map<string, ParserSearchConfig>();

  for (const config of normalizedConfigs) {
    uniqueConfigs.set(config.id, config);
  }

  return Array.from(uniqueConfigs.values());
}

function parserSearchFiltersFromForm(
  form: ParserSearchForm,
  currentFilters: Record<string, unknown> = {},
): Record<string, unknown> {
  const versioned =
    isRecord(currentFilters.search) ||
    isRecord(currentFilters.screening);
  const currentSearch = versioned && isRecord(currentFilters.search)
    ? currentFilters.search
    : versioned
      ? {}
      : currentFilters;
  const currentScreening = isRecord(currentFilters.screening)
    ? currentFilters.screening
    : null;
  return {
    ...(versioned ? currentFilters : {}),
    schemaVersion: 2,
    search: {
      ...currentSearch,
      keywords: form.keywords.trim(),
      location: form.location.trim(),
      remote: form.remote,
      experienceLevel: form.experienceLevel,
      jobType: form.jobType,
      datePosted: form.datePosted,
      resultsLimit: Number.parseInt(form.resultsLimit, 10) || 10,
      country: form.country,
      deduplicate: form.deduplicate,
      searchName: form.searchName.trim(),
      folder: form.folder,
      sources: normalizeParserIds(form),
    },
    screening: currentScreening ?? {
      enabled: true,
      targetRoles: form.keywords.trim() ? [form.keywords.trim()] : [],
      excludedRoles: [],
      allowedSeniority: [],
      excludedSeniority: [],
      hardRules: [],
    },
  };
}

function parserSearchConfigFromApi(
  config: JobSearchConfigPayload,
): ParserSearchConfig {
  const filters = config.filters;
  const searchFilters = isRecord(filters.search)
    ? filters.search
    : filters;
  const sources = Array.isArray(searchFilters.sources)
    ? searchFilters.sources.filter(
        (source): source is ParserId =>
          source === "linkedin" || source === "indeed" || source === "jobs_ch",
      )
    : [];
  return {
    id: config.id,
    name: config.name,
    filters,
    updatedAt: config.updatedAt,
    form: {
      ...defaultParserSearchForm,
      parsers: sources.length > 0 ? sources : [...defaultParserSearchForm.parsers],
      keywords: filterString(searchFilters, "keywords"),
      location: filterString(searchFilters, "location"),
      remote:
        filterString(searchFilters, "remote") ||
        defaultParserSearchForm.remote,
      experienceLevel:
        filterString(
          searchFilters,
          "experienceLevel",
          "experience_level",
        ) ||
        defaultParserSearchForm.experienceLevel,
      jobType:
        filterString(searchFilters, "jobType", "job_type") ||
        defaultParserSearchForm.jobType,
      datePosted:
        filterString(searchFilters, "datePosted", "date_posted") ||
        defaultParserSearchForm.datePosted,
      resultsLimit: String(
        filterNumber(
          searchFilters,
          "resultsLimit",
          "results_limit",
        ) ?? 10,
      ),
      country:
        filterString(searchFilters, "country") ||
        defaultParserSearchForm.country,
      deduplicate:
        filterBoolean(searchFilters, "deduplicate") ??
        defaultParserSearchForm.deduplicate,
      searchName: config.name,
      folder: filterString(searchFilters, "folder"),
    },
  };
}

function filterString(
  filters: Record<string, unknown>,
  ...keys: string[]
): string {
  for (const key of keys) {
    if (typeof filters[key] === "string") return filters[key];
  }
  return "";
}

function filterNumber(
  filters: Record<string, unknown>,
  ...keys: string[]
): number | null {
  for (const key of keys) {
    const value = filters[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && Number.isFinite(Number(value))) {
      return Number(value);
    }
  }
  return null;
}

function filterBoolean(
  filters: Record<string, unknown>,
  key: string,
): boolean | null {
  return typeof filters[key] === "boolean" ? filters[key] : null;
}

function normalizeStoredLogs(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value
    .filter((entry): entry is Partial<AppLogEntry> => Boolean(entry) && typeof entry === "object")
    .map((entry) => ({
      id: typeof entry.id === "string" && entry.id ? entry.id : createClientId("log"),
      timestamp: typeof entry.timestamp === "string" && entry.timestamp ? entry.timestamp : new Date().toISOString(),
      level: isAppLogLevel(entry.level) ? entry.level : "info",
      area: typeof entry.area === "string" && entry.area ? entry.area : "Application",
      message: typeof entry.message === "string" && entry.message ? entry.message : "Log entry",
      details: typeof entry.details === "string" && entry.details ? entry.details : undefined,
    }))
    .slice(0, maxStoredAppLogs);
}

function isAppLogLevel(value: unknown): value is AppLogLevel {
  return value === "info" || value === "success" || value === "warning" || value === "error";
}

function formatLogTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time unknown";

  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatAiMatchTimestamp(value?: string) {
  if (!value) return "Not calculated yet";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time unknown";

  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const aiMatchBreakdownItems = [
  { key: "role_fit", label: "Role", max: 20 },
  { key: "skills_fit", label: "Skills", max: 30 },
  { key: "experience_fit", label: "Experience", max: 15 },
  { key: "preferences_fit", label: "Preferences", max: 15 },
  { key: "constraints_fit", label: "Constraints", max: 10 },
  { key: "industry_fit", label: "Industry", max: 5 },
  { key: "evidence_fit", label: "Evidence", max: 5 },
];

function getAiMatchBreakdownItems(job: Job) {
  const breakdown = job.aiMatch?.breakdown ?? {};
  return aiMatchBreakdownItems.map(({ key, label, max }) => {
    const value = Math.max(0, Math.min(max, Math.round(Number(breakdown[key] ?? 0))));
    return {
      key,
      label,
      value,
      max,
      progress: Math.round((value / max) * 100),
    };
  });
}

function getAiMatchSourceLabel(job: Job) {
  if (job.aiMatch?.source === "openclaw_codex" || job.aiMatch?.source === "openai_api") {
    return getAiSourceLabel(job.aiMatch.source);
  }
  if (job.aiMatch?.source === "local") return "Legacy local score";
  if (isImportedJob(job)) return "Not scored";
  if (isManualJob(job)) return "Not scored";
  return "Static score";
}

function getAiMatchSourceStatus(job: Job) {
  if (!job.aiMatch?.providerError) return "";
  return "Provider fallback/error";
}

function getAiMatchSourceDisplay(job: Job) {
  const sourceLabel = getAiMatchSourceLabel(job);
  const sourceStatus = getAiMatchSourceStatus(job);
  return sourceStatus ? `${sourceLabel} · ${sourceStatus}` : sourceLabel;
}

function formatConfidence(value?: AiMatchMetadata["confidence"]) {
  if (!value) return "Not calculated";
  return `${value[0].toUpperCase()}${value.slice(1)}`;
}

function buildAiMatchRawExplanation(job: Job) {
  if (job.aiMatch?.rawExplanation) return job.aiMatch.rawExplanation;
  if (job.aiMatch?.explanation) return job.aiMatch.explanation;
  if (job.aiMatch?.providerError) return `Provider fallback: ${job.aiMatch.providerError}`;
  if (!hasDisplayableMatch(job)) return "AI match has not been calculated for this vacancy yet.";

  const source = getAiMatchSourceLabel(job);
  const reasons = job.aiMatch?.reasons.length ? job.aiMatch.reasons.join("; ") : "no AI-generated reasons are available";
  const gaps = job.aiMatch?.gaps.length ? job.aiMatch.gaps.join("; ") : "no major gaps detected";

  return `${source} calculated a ${job.match}% match for ${job.title} at ${job.company}. Reasons: ${reasons}. Gaps: ${gaps}.`;
}

function getProfileImprovementItems(job: Job) {
  const evidence = job.aiMatch?.applicationGuide?.evidenceMatrix ?? [];
  return evidence
    .filter((item) => ["verified", "transferable"].includes(item.status) && item.sources?.length)
    .map((item) => `${item.action} Sources: ${item.sources?.map((source) => `${source.label} — “${source.excerpt}”`).join("; ")}.`)
    .slice(0, 5);
}

function buildRecommendationPlan(job: Job): JobRecommendation[] {
  const evidence = job.aiMatch?.applicationGuide?.evidenceMatrix ?? [];
  return evidence
    .filter((item) => ["verified", "transferable"].includes(item.status) && item.sources?.length)
    .map((item) => ({
      text: item.action,
      gain: item.status === "verified" ? "verified evidence" : "transferable evidence",
      why: `${item.requirement}: ${item.evidence}`,
      impact: `Sources: ${item.sources?.map((source) => source.label).join(", ")}`,
      action: item.sources?.map((source) => `${source.label}: “${source.excerpt}”`).join(" · "),
    }))
    .slice(0, 9);
}

function isImportedJob(job: Job) {
  return job.id.startsWith("linkedin-") || job.id.startsWith("indeed-") || job.id.startsWith("jobs_ch-");
}

function isManualJob(job: Job) {
  return job.id.startsWith("manual-job-");
}

function isUserManagedJob(job: Job) {
  return isImportedJob(job) || isManualJob(job);
}

function hasAiBackendMatch(job: Job) {
  return job.aiMatch?.source === "openclaw_codex" || job.aiMatch?.source === "openai_api";
}

function hasDisplayableMatch(job: Job) {
  return (!isImportedJob(job) && !isManualJob(job)) || hasAiBackendMatch(job);
}

function formatMatchValue(job: Job) {
  return hasDisplayableMatch(job) ? `${job.match}%` : "Not scored";
}

function getDisplayMatch(job: Job) {
  return hasDisplayableMatch(job) ? job.match : 0;
}

function sanitizeLegacyLocalAiMatch(job: Job): Job {
  if (job.aiMatch?.source !== "local" || job.aiMatch.version === legacyAiMatchVersion) return job;

  const { aiMatch: _legacyAiMatch, ...jobWithoutLegacyAiMatch } = job;
  return {
    ...jobWithoutLegacyAiMatch,
    match: 50,
  };
}

function normalizeStoredJobs(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((job): Job[] => {
    if (!job || typeof job !== "object") return [];
    const candidate = job as Partial<Job>;
    const isValidJob =
      typeof candidate.id === "string" &&
      typeof candidate.company === "string" &&
      typeof candidate.title === "string" &&
      typeof candidate.location === "string" &&
      typeof candidate.type === "string" &&
      typeof candidate.salary === "string" &&
      typeof candidate.posted === "string" &&
      typeof candidate.experience === "string" &&
      typeof candidate.department === "string" &&
      typeof candidate.match === "number" &&
      (
        candidate.logo === "stripe" ||
        candidate.logo === "figma" ||
        candidate.logo === "linkedin" ||
        candidate.logo === "indeed" ||
        candidate.logo === "jobs_ch" ||
        candidate.logo === "manual"
      ) &&
      typeof candidate.overview === "string" &&
      Array.isArray(candidate.responsibilities) &&
      Array.isArray(candidate.requirements) &&
      Array.isArray(candidate.skills);

    if (!isValidJob) return [];

    return [
      sanitizeLegacyLocalAiMatch({
        ...(candidate as Job),
        logo: normalizeStoredJobLogo(candidate as Job),
        archived: Boolean(candidate.archived),
        archivedAt: typeof candidate.archivedAt === "string" ? candidate.archivedAt : undefined,
      }),
    ];
  });
}

function normalizeStoredJobLogo(job: Job): Job["logo"] {
  if (job.id.startsWith("linkedin-")) return "linkedin";
  if (job.id.startsWith("indeed-")) return "indeed";
  if (job.id.startsWith("jobs_ch-")) return "jobs_ch";
  return job.logo;
}

function normalizeStoredJobIds(value: unknown) {
  if (!Array.isArray(value)) return [];

  return Array.from(new Set(value.filter((id): id is string => typeof id === "string" && id.trim().length > 0)));
}

function normalizeApplicationDocuments(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((document): ApplicationDocument[] => {
    if (!document || typeof document !== "object") return [];
    const candidate = document as Partial<ApplicationDocument>;
    const fileName = candidate.fileName?.trim() ?? "";
    const dataUrl = candidate.dataUrl ?? "";

    if (typeof candidate.id !== "string" || !fileName || typeof dataUrl !== "string" || !dataUrl) {
      return [];
    }

    return [
      {
        id: candidate.id,
        artifactId: candidate.artifactId?.trim() || undefined,
        title: candidate.title?.trim() || fileName.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() || fileName,
        fileName,
        fileSize: candidate.fileSize?.trim() ?? "",
        fileType: candidate.fileType?.trim() ?? "application/octet-stream",
        uploadedAt: candidate.uploadedAt?.trim() ?? "",
        dataUrl,
      },
    ];
  });
}

function normalizeStoredApplications(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((application): TrackedApplication[] => {
    if (!application || typeof application !== "object") return [];
    const candidate = application as Partial<TrackedApplication>;
    const normalizedJobs = normalizeStoredJobs([candidate.job]);
    const isValidApplication =
      typeof candidate.id === "string" &&
      candidate.job !== undefined &&
      normalizedJobs.length === 1 &&
      applicationStatuses.some((item) => item.status === candidate.status) &&
      typeof candidate.appliedAt === "string" &&
      typeof candidate.nextStep === "string" &&
      typeof candidate.notes === "string";

    if (!isValidApplication) return [];

    const id = candidate.id as string;
    const appliedAt = candidate.appliedAt as string;
    const nextStep = candidate.nextStep as string;
    const notes = candidate.notes as string;

    return [
      {
        id,
        job: normalizedJobs[0],
        status: candidate.status as ApplicationStatus,
        appliedAt,
        nextStep,
        notes,
        documents: normalizeApplicationDocuments(candidate.documents),
      },
    ];
  });
}

function removeLegacyDemoApplications(applications: TrackedApplication[]) {
  return applications.filter((application) => !legacyDemoApplicationIds.has(application.id));
}

function normalizeStoredApplicationEvents(value: unknown) {
  if (!Array.isArray(value)) return [];

  return value.flatMap((event): ApplicationEvent[] => {
    if (!event || typeof event !== "object") return [];
    const candidate = event as Partial<ApplicationEvent>;
    const { id, applicationId, type, title, startsAt, durationMinutes, timezone, location, notes } = candidate;

    if (
      typeof id !== "string" ||
      typeof applicationId !== "string" ||
      !type ||
      !applicationEventTypes.some((item) => item.type === type) ||
      typeof title !== "string" ||
      typeof startsAt !== "string" ||
      typeof durationMinutes !== "number" ||
      typeof timezone !== "string" ||
      typeof location !== "string" ||
      typeof notes !== "string"
    ) {
      return [];
    }

    const storedStatus = candidate.status;
    const storedOutcome = candidate.outcome;
    const status: ApplicationEventStatus = applicationEventStatuses.some((item) => item.status === storedStatus) && storedStatus
      ? storedStatus
      : "scheduled";
    const outcome = applicationEventOutcomes.some((item) => item.outcome === storedOutcome)
      ? storedOutcome
      : undefined;

    return [
      {
        id,
        applicationId,
        type,
        status,
        outcome,
        title,
        startsAt,
        durationMinutes,
        timezone,
        location,
        notes,
      },
    ];
  });
}

function createApplicationFromJob(job: Job, status: ApplicationStatus = "applied"): TrackedApplication {
  const appliedAt = new Date().toISOString();

  return {
    id: `application-${job.id}`,
    job,
    status,
    appliedAt,
    nextStep: "",
    notes: "",
    documents: [],
  };
}

function createApplicationFromManualDraft(draft: ManualApplicationDraft): TrackedApplication {
  const job = createManualJobFromDraft(draft);

  return {
    id: `application-${job.id}`,
    job,
    status: draft.status,
    appliedAt: new Date().toISOString(),
    nextStep: "",
    notes: "",
    documents: draft.documents,
  };
}

function createProfileResumeApplicationDocument(profile: CandidateProfile): ApplicationDocument | null {
  if (!profile.resume_file_name || !profile.resume_data_url) return null;

  return {
    id: createClientId("profile-resume"),
    title: profile.resume_file_name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() || "Profile resume",
    fileName: profile.resume_file_name,
    fileSize: profile.resume_file_size,
    fileType: "application/octet-stream",
    uploadedAt: profile.resume_updated_at || new Date().toISOString(),
    dataUrl: profile.resume_data_url,
  };
}

function getJobApplyUrl(job: Job) {
  return job.applyUrl || job.sourceUrl || "";
}

function getApplicationEventTypeLabel(type: ApplicationEventType) {
  return applicationEventTypes.find((item) => item.type === type)?.label ?? type;
}

function getApplicationEventStatusLabel(status: ApplicationEventStatus) {
  return applicationEventStatuses.find((item) => item.status === status)?.label ?? status;
}

function getApplicationEventOutcomeLabel(outcome?: ApplicationEventOutcome) {
  return outcome ? applicationEventOutcomes.find((item) => item.outcome === outcome)?.label ?? outcome : "";
}

function getApplicationTimelineEventLabel(type: ApplicationEventType) {
  const labels: Record<ApplicationEventType, string> = {
    screening: "Phone screen",
    interview: "Interview",
    assessment: "Assessment deadline",
    follow_up: "Follow-up",
    offer_deadline: "Offer deadline",
  };

  return labels[type];
}

function getLocalTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function toDateTimeLocalValue(date: Date) {
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function createDefaultEventDraft(application: TrackedApplication): ApplicationEventDraft {
  const start = new Date();
  start.setDate(start.getDate() + 5);
  start.setHours(10, 0, 0, 0);

  return {
    type: "screening",
    status: "scheduled",
    outcome: "",
    title: `${application.job.company} screening`,
    startsAt: toDateTimeLocalValue(start),
    durationMinutes: "30",
    timezone: getLocalTimezone(),
    location: "",
    notes: "",
  };
}

function createEventDraftFromEvent(event: ApplicationEvent): ApplicationEventDraft {
  return {
    id: event.id,
    type: event.type,
    status: event.status,
    outcome: event.outcome ?? "",
    title: event.title,
    startsAt: toDateTimeLocalValue(new Date(event.startsAt)),
    durationMinutes: event.durationMinutes.toString(),
    timezone: event.timezone,
    location: event.location,
    notes: event.notes,
  };
}

function createApplicationEvent(applicationId: string, draft: ApplicationEventDraft): ApplicationEvent {
  const startDate = new Date(draft.startsAt);
  const startsAt = Number.isNaN(startDate.getTime()) ? new Date().toISOString() : startDate.toISOString();

  return {
    id: draft.id ?? createClientId("application-event"),
    applicationId,
    type: draft.type,
    status: draft.status,
    outcome: draft.status === "completed" ? draft.outcome || undefined : undefined,
    title: draft.title.trim() || getApplicationEventTypeLabel(draft.type),
    startsAt,
    durationMinutes: Number.parseInt(draft.durationMinutes, 10) || 30,
    timezone: draft.timezone.trim() || getLocalTimezone(),
    location: draft.location.trim(),
    notes: draft.notes.trim(),
  };
}

function sortApplicationEvents(events: ApplicationEvent[]) {
  return [...events].sort((a, b) => new Date(a.startsAt).getTime() - new Date(b.startsAt).getTime());
}

function formatApplicationEventDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date TBD";

  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatApplicationEventTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time TBD";

  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function formatApplicationDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not set";

  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][date.getMonth()];
  return `${month} ${date.getDate()}, ${date.getFullYear()}`;
}

function getApplicationStatusLabel(status: ApplicationStatus) {
  return applicationStatuses.find((item) => item.status === status)?.label ?? status;
}

function getVisibleApplicationNotes(notes: string) {
  return notes.trim() === legacyMovedFromJobsNote ? "" : notes.trim();
}

function mergeJobs(importedJobs: Job[], currentJobs: Job[]) {
  const importedIds = new Set(importedJobs.map((job) => job.id));
  return [...importedJobs, ...currentJobs.filter((job) => !importedIds.has(job.id))];
}

function keepStoredUserJobs(jobs: Job[]) {
  return jobs.filter(isUserManagedJob);
}

function hasActiveJobFilters(filters: JobFilters) {
  return Object.values(filters).some((value) => value !== "Any");
}

function parseSalaryAmount(value: string) {
  if (!value || value === "N/A") return 0;

  const hasThousandsSuffix = /k/i.test(value);
  const amounts = value.match(/\d+(?:[,.]\d+)?/g)?.map((amount) => {
    const normalizedAmount = Number.parseFloat(amount.replace(/,/g, ""));
    if (Number.isNaN(normalizedAmount)) return 0;
    return hasThousandsSuffix ? normalizedAmount * 1000 : normalizedAmount;
  });

  return amounts?.length ? Math.max(...amounts) : 0;
}

function getJobSalaryAmount(job: Job) {
  return parseSalaryAmount(job.salaryAverage) || parseSalaryAmount(job.salaryMax) || parseSalaryAmount(job.salary);
}

function getRelativePostedTime(value: string) {
  const normalizedValue = value.trim().toLowerCase();
  const relativeMatch = normalizedValue.match(/^(\d+)\s*([hdw])(?:\s+ago)?$/);
  if (!relativeMatch) return 0;

  const amount = Number.parseInt(relativeMatch[1], 10);
  const unit = relativeMatch[2];
  const multiplier = unit === "h" ? 60 * 60 * 1000 : unit === "d" ? 24 * 60 * 60 * 1000 : 7 * 24 * 60 * 60 * 1000;

  return Date.now() - amount * multiplier;
}

function getJobPostedTime(job: Job) {
  const parsedDate = Date.parse(job.posted);
  if (!Number.isNaN(parsedDate)) return parsedDate;

  return getRelativePostedTime(job.posted);
}

function getBulkAnalysisCandidates(jobsToCheck: Job[], scope: BulkAnalysisScope) {
  const recentCutoff = Date.now() - recentJobWindowMs;

  return jobsToCheck.filter((job) => {
    if (job.archived) return false;
    if (scope === "missing") return getAiMatchAnalysisStatus(job.aiMatch) !== "current";

    const addedAt = Date.parse(job.addedAt ?? "");
    return !Number.isNaN(addedAt) && addedAt >= recentCutoff;
  });
}

function formatJobPosted(value: string) {
  const parsedDate = Date.parse(value);
  if (!Number.isNaN(parsedDate)) {
    return new Intl.DateTimeFormat("de-CH", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(parsedDate));
  }

  return value.replace(/^(\d+)h ago$/i, "$1 hours ago").replace(/^(\d+)d ago$/i, "$1 days ago");
}

function formatJobPostedCompact(value: string) {
  const parsedDate = Date.parse(value);
  if (!Number.isNaN(parsedDate)) {
    const parsedDateValue = new Date(parsedDate);
    const day = parsedDateValue.getDate().toString().padStart(2, "0");
    const month = (parsedDateValue.getMonth() + 1).toString().padStart(2, "0");
    const date = `${day}.${month}`;
    const time = new Intl.DateTimeFormat("de-CH", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(parsedDateValue);

    return `${date} • ${time}`;
  }

  return formatJobPosted(value);
}

function formatJobLocationCompact(value: string) {
  return value.split(",")[0]?.trim() || value;
}

function getJobExperienceYears(job: Job) {
  const normalizedExperience = job.experience.toLowerCase();
  const explicitYears = normalizedExperience.match(/\d+/)?.[0];

  if (explicitYears) return Number.parseInt(explicitYears, 10);
  if (normalizedExperience.includes("director") || normalizedExperience.includes("lead") || normalizedExperience.includes("principal")) return 7;
  if (normalizedExperience.includes("senior")) return 5;
  if (normalizedExperience.includes("mid")) return 3;
  if (normalizedExperience.includes("associate")) return 1;
  if (normalizedExperience.includes("entry") || normalizedExperience.includes("junior") || normalizedExperience.includes("intern")) return 0;

  return null;
}

function matchesExperienceFilter(job: Job, filter: string) {
  if (filter === "Any") return true;

  const years = getJobExperienceYears(job);
  const normalizedExperience = job.experience.toLowerCase();

  if (filter === "entry") {
    return (
      (years !== null && years <= 2) ||
      normalizedExperience.includes("entry") ||
      normalizedExperience.includes("junior") ||
      normalizedExperience.includes("associate") ||
      normalizedExperience.includes("intern")
    );
  }

  if (filter === "mid") {
    return (years !== null && years >= 2 && years < 5) || normalizedExperience.includes("mid");
  }

  if (filter === "senior") {
    return (
      (years !== null && years >= 5) ||
      normalizedExperience.includes("senior") ||
      normalizedExperience.includes("director") ||
      normalizedExperience.includes("lead") ||
      normalizedExperience.includes("principal")
    );
  }

  return true;
}

function matchesRemoteFilter(job: Job, filter: string) {
  if (filter === "Any") return true;

  const searchableText = [job.location, job.type, job.overview, job.department].join(" ").toLowerCase();

  if (filter === "remote") return searchableText.includes("remote");
  if (filter === "hybrid") return searchableText.includes("hybrid");
  if (filter === "onsite") {
    return (
      searchableText.includes("on-site") ||
      searchableText.includes("onsite") ||
      searchableText.includes("office") ||
      (!searchableText.includes("remote") && !searchableText.includes("hybrid"))
    );
  }

  return true;
}

function matchesJobFilters(job: Job, filters: JobFilters) {
  const salaryAmount = getJobSalaryAmount(job);

  return (
    (filters.location === "Any" || job.location.toLowerCase().includes(filters.location.toLowerCase())) &&
    matchesRemoteFilter(job, filters.remote) &&
    (filters.salary === "Any" ||
      (filters.salary === "listed" ? salaryAmount > 0 : salaryAmount >= Number.parseInt(filters.salary, 10))) &&
    matchesExperienceFilter(job, filters.experience) &&
    (filters.type === "Any" || job.type === filters.type) &&
    (filters.match === "Any" || getDisplayMatch(job) >= Number.parseInt(filters.match, 10))
  );
}

function mergeSkillLists(currentSkills: string[], importedSkills: string[]) {
  return Array.from(
    new Map(
      [...currentSkills, ...importedSkills]
        .map((skill) => skill.trim())
        .filter(Boolean)
        .map((skill) => [skill.toLowerCase(), skill]),
    ).values(),
  );
}

export default function HomePage() {
  const [activeView, setActiveView] = useState<View>("Dashboard");
  const [assistantLaunch, setAssistantLaunch] = useState<AssistantLaunch | null>(null);
  const [jobList, setJobList] = useState<Job[]>(jobs);
  const [selectedJobId, setSelectedJobId] = useState(jobs[0].id);
  const [query, setQuery] = useState("");
  const [activeTab, setActiveTab] = useState(tabs[0]);
  const [pendingAiMatchFocus, setPendingAiMatchFocus] = useState<"analysis" | "recommendations" | null>(null);
  const aiMatchAnalysisRef = useRef<HTMLElement | null>(null);
  const aiMatchRecommendationsRef = useRef<HTMLElement | null>(null);
  const [savedJobs, setSavedJobs] = useState<string[]>([]);
  const [areSavedJobsLoaded, setAreSavedJobsLoaded] = useState(false);
  const [archivedJobIds, setArchivedJobIds] = useState<string[]>([]);
  const [deletedJobIds, setDeletedJobIds] = useState<string[]>([]);
  const [showSavedJobs, setShowSavedJobs] = useState(false);
  const [showArchivedJobs, setShowArchivedJobs] = useState(false);
  const [applications, setApplications] = useState<TrackedApplication[]>([]);
  const [selectedApplicationId, setSelectedApplicationId] = useState("");
  const [workspaceApplicationId, setWorkspaceApplicationId] = useState<string | null>(null);
  const [areApplicationsLoaded, setAreApplicationsLoaded] = useState(false);
  const [matchingApplicationIds, setMatchingApplicationIds] = useState<string[]>([]);
  const [applicationEvents, setApplicationEvents] = useState<ApplicationEvent[]>([]);
  const [areApplicationEventsLoaded, setAreApplicationEventsLoaded] = useState(false);
  const [jobFilters, setJobFilters] = useState<JobFilters>(defaultJobFilters);
  const [sortBy, setSortBy] = useState<JobSortBy>("AI Match");
  const [isAnalysisMenuOpen, setIsAnalysisMenuOpen] = useState(false);
  const [bulkAnalysisScope, setBulkAnalysisScope] = useState<BulkAnalysisScope | null>(null);
  const [isManualJobDialogOpen, setIsManualJobDialogOpen] = useState(false);
  const [manualJobDraft, setManualJobDraft] = useState<ManualJobDraft>(defaultManualJobDraft);
  const [isParserDialogOpen, setIsParserDialogOpen] = useState(false);
  const [parserSearchStatus, setParserSearchStatus] = useState<ParserSearchStatus>("idle");
  const [parserSearchMessage, setParserSearchMessage] = useState("");
  const [forceMatchingJobId, setForceMatchingJobId] = useState("");
  const [aiMatchErrorMessage, setAiMatchErrorMessage] = useState("");
  const [matchFeedbackSavingJobId, setMatchFeedbackSavingJobId] = useState("");
  const [parserSearchForm, setParserSearchForm] = useState<ParserSearchForm>(defaultParserSearchForm);
  const [parserSearchConfigs, setParserSearchConfigs] = useState<ParserSearchConfig[]>([]);
  const [selectedParserSearchConfigId, setSelectedParserSearchConfigId] = useState("");
  const [profile, setProfile] = useState<CandidateProfile>(defaultCandidateProfile);
  const [profileDraft, setProfileDraft] = useState<CandidateProfile>(defaultCandidateProfile);
  const [isProfileLoaded, setIsProfileLoaded] = useState(false);
  const [isProfileDialogOpen, setIsProfileDialogOpen] = useState(false);
  const [isExperienceDialogOpen, setIsExperienceDialogOpen] = useState(false);
  const [isExperienceEditMode, setIsExperienceEditMode] = useState(false);
  const [experienceDraft, setExperienceDraft] = useState<ExperienceEntry>(defaultExperienceDraft);
  const [isExperienceImporting, setIsExperienceImporting] = useState(false);
  const [experienceImportMessage, setExperienceImportMessage] = useState("");
  const [isEducationDialogOpen, setIsEducationDialogOpen] = useState(false);
  const [isEducationEditMode, setIsEducationEditMode] = useState(false);
  const [educationDraft, setEducationDraft] = useState<EducationEntry>(defaultEducationDraft);
  const [isEducationImporting, setIsEducationImporting] = useState(false);
  const [educationImportMessage, setEducationImportMessage] = useState("");
  const [isDocumentDialogOpen, setIsDocumentDialogOpen] = useState(false);
  const [isDocumentEditMode, setIsDocumentEditMode] = useState(false);
  const [documentDraft, setDocumentDraft] = useState<DocumentEntry>(defaultDocumentDraft);
  const [isPreferencesDialogOpen, setIsPreferencesDialogOpen] = useState(false);
  const [preferencesDraft, setPreferencesDraft] = useState<JobPreferences>(defaultJobPreferences);
  const [preferenceInputs, setPreferenceInputs] = useState<PreferenceInputs>(defaultPreferenceInputs);
  const [isSkillsDialogOpen, setIsSkillsDialogOpen] = useState(false);
  const [skillsDraft, setSkillsDraft] = useState<string[]>([]);
  const [skillInput, setSkillInput] = useState("");
  const [isSkillsImporting, setIsSkillsImporting] = useState(false);
  const [skillsImportMessage, setSkillsImportMessage] = useState("");
  const [isDealbreakersDialogOpen, setIsDealbreakersDialogOpen] = useState(false);
  const [dealbreakersDraft, setDealbreakersDraft] = useState<string[]>([]);
  const [dealbreakerInput, setDealbreakerInput] = useState("");
  const [isAdditionalNotesDialogOpen, setIsAdditionalNotesDialogOpen] = useState(false);
  const [additionalNotesDraft, setAdditionalNotesDraft] = useState("");
  const [profileSaveStatus, setProfileSaveStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [profileSaveMessage, setProfileSaveMessage] = useState("");
  const [appSettings, setAppSettings] = useState<AppSettings>(defaultAppSettings);
  const [brightDataApiKeyDraft, setBrightDataApiKeyDraft] = useState("");
  const [settingsSaveStatus, setSettingsSaveStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [settingsSaveMessage, setSettingsSaveMessage] = useState("");
  const [aiSettingsSaveStatus, setAiSettingsSaveStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [aiSettingsSaveMessage, setAiSettingsSaveMessage] = useState("");
  const [uiSettings, setUiSettings] = useState<UiSettings>(defaultUiSettings);
  const [areUiSettingsLoaded, setAreUiSettingsLoaded] = useState(false);
  const [appLogs, setAppLogs] = useState<AppLogEntry[]>([]);
  const [areAppLogsLoaded, setAreAppLogsLoaded] = useState(false);
  const availableJobs = useMemo(
    () =>
      jobList
        .filter((job) => !deletedJobIds.includes(job.id))
        .map((job) => ({
          ...job,
          archived: job.archived || archivedJobIds.includes(job.id),
        })),
    [archivedJobIds, deletedJobIds, jobList],
  );

  const archivedJobsCount = useMemo(() => availableJobs.filter((job) => job.archived).length, [availableJobs]);
  const savedJobsCount = useMemo(
    () => availableJobs.filter((job) => !job.archived && savedJobs.includes(job.id)).length,
    [availableJobs, savedJobs],
  );
  const recentAnalysisJobs = getBulkAnalysisCandidates(availableJobs, "recent");
  const missingAnalysisJobs = getBulkAnalysisCandidates(availableJobs, "missing");

  const locationFilterOptions = useMemo(
    () =>
      Array.from(new Set(availableJobs.map((job) => job.location.trim()).filter(Boolean)))
        .sort((a, b) => a.localeCompare(b))
        .map((location) => ({ value: location, label: location })),
    [availableJobs],
  );

  const typeFilterOptions = useMemo(
    () =>
      Array.from(new Set(availableJobs.map((job) => job.type.trim()).filter(Boolean)))
        .sort((a, b) => a.localeCompare(b))
        .map((type) => ({ value: type, label: type })),
    [availableJobs],
  );

  const jobFilterControls: Array<{
    key: JobFilterKey;
    label: string;
    options: Array<{ value: string; label: string }>;
  }> = [
    { key: "location", label: "Location", options: locationFilterOptions },
    { key: "remote", label: "Remote", options: remoteFilterOptions },
    { key: "salary", label: "Salary", options: salaryFilterOptions },
    { key: "experience", label: "Experience", options: experienceFilterOptions },
    { key: "type", label: "Job Type", options: typeFilterOptions },
    { key: "match", label: "AI Match", options: matchFilterOptions },
  ];

  const filteredJobs = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const jobsForCurrentMode = availableJobs
      .filter((job) => Boolean(job.archived) === showArchivedJobs)
      .filter((job) => !showSavedJobs || savedJobs.includes(job.id))
      .filter((job) => matchesJobFilters(job, jobFilters));
    const results = normalizedQuery
      ? jobsForCurrentMode.filter((job) =>
          [job.title, job.company, job.location, job.type, job.salary].some((value) =>
            value.toLowerCase().includes(normalizedQuery),
          ),
        )
      : jobsForCurrentMode;

    return [...results].sort((a, b) => {
      if (sortBy === "Time") return getJobPostedTime(b) - getJobPostedTime(a);
      if (sortBy === "Salary") {
        return getJobSalaryAmount(b) - getJobSalaryAmount(a);
      }
      return getDisplayMatch(b) - getDisplayMatch(a);
    });
  }, [availableJobs, jobFilters, query, savedJobs, showArchivedJobs, showSavedJobs, sortBy]);

  const selectedJob = filteredJobs.find((job) => job.id === selectedJobId) ?? filteredJobs[0] ?? null;
  const isSelectedSaved = selectedJob ? savedJobs.includes(selectedJob.id) : false;
  const selectedJobPreparation = selectedJob
    ? applications.find((application) => application.job.id === selectedJob.id)
    : undefined;
  const selectedJobApplication = selectedJobPreparation?.status === "draft" ? undefined : selectedJobPreparation;
  const trackedApplications = useMemo(
    () => applications.filter((application) => application.status !== "draft"),
    [applications],
  );
  const trackedApplicationIds = useMemo(
    () => new Set(trackedApplications.map((application) => application.id)),
    [trackedApplications],
  );
  const trackedApplicationEvents = useMemo(
    () => applicationEvents.filter((event) => trackedApplicationIds.has(event.applicationId)),
    [applicationEvents, trackedApplicationIds],
  );
  const selectedApplication = trackedApplications.find((application) => application.id === selectedApplicationId) ?? trackedApplications[0] ?? null;
  const workspaceApplication = findWorkspaceApplication(applications, workspaceApplicationId);

  function openAiMatchSection(section: "analysis" | "recommendations") {
    setActiveTab("AI Match");
    setPendingAiMatchFocus(section);
  }

  async function refreshStoredJobsFromServer(signal?: AbortSignal) {
    const response = await fetch(`${apiBaseUrl}/jobs`, {
      cache: "no-store",
      signal,
    });
    if (!response.ok) {
      throw new Error(
        await readApiErrorMessage(response, "Vacancies could not be refreshed"),
      );
    }

    const storedJobs = (await response.json()) as Array<{
      id: string;
      data: unknown;
    }>;
    const storedUserJobs = keepStoredUserJobs(
      normalizeStoredJobs(storedJobs.map((job) => job.data)),
    );
    setJobList((currentJobs) => [
      ...storedUserJobs,
      ...currentJobs.filter((job) => !isUserManagedJob(job)),
    ]);
    window.localStorage.setItem(
      importedJobsStorageKey,
      JSON.stringify(storedUserJobs),
    );
    return storedUserJobs;
  }

  useEffect(() => {
    if (!screenshotSessionId) return;
    if (
      window.localStorage.getItem(screenshotSessionStorageKey) ===
      screenshotSessionId
    ) {
      return;
    }

    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith("tasko.")) {
        window.localStorage.removeItem(key);
      }
    }
    window.localStorage.setItem(screenshotSessionStorageKey, screenshotSessionId);
  }, []);

  useEffect(() => {
    if (activeTab !== "AI Match" || !pendingAiMatchFocus) return;

    const frame = window.requestAnimationFrame(() => {
      const target = pendingAiMatchFocus === "recommendations" ? aiMatchRecommendationsRef.current : aiMatchAnalysisRef.current;
      target?.scrollIntoView({ behavior: "smooth", block: "start" });
      target?.focus({ preventScroll: true });
      setPendingAiMatchFocus(null);
    });

    return () => window.cancelAnimationFrame(frame);
  }, [activeTab, pendingAiMatchFocus, selectedJob?.id]);

  useEffect(() => {
    const syncViewFromHash = () => {
      const route = getRouteFromHash(window.location.hash);

      setActiveView(route.view);
      if (route.view === "ApplicationWorkspace") {
        setWorkspaceApplicationId(route.applicationId ?? null);
      } else {
        setWorkspaceApplicationId(null);
      }
      if (route.applicationId) {
        setSelectedApplicationId(route.applicationId);
      }
    };

    syncViewFromHash();
    window.addEventListener("hashchange", syncViewFromHash);
    return () => window.removeEventListener("hashchange", syncViewFromHash);
  }, []);

  useEffect(() => {
    let isMounted = true;

    async function loadParserSearchConfigs() {
      try {
        window.localStorage.removeItem(legacyParserSearchConfigsStorageKey);
        const response = await fetch(`${apiBaseUrl}/job-search/configs`, {
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(
            await readApiErrorMessage(response, "Search configs could not be loaded"),
          );
        }
        const serverConfigs = (await response.json()) as JobSearchConfigPayload[];
        const rawLegacyConfigs = window.localStorage.getItem(
          parserSearchConfigsStorageKey,
        );

        if (rawLegacyConfigs) {
          let legacyConfigs: ParserSearchConfig[] = [];
          try {
            const parsedLegacyConfigs = JSON.parse(rawLegacyConfigs) as unknown;
            legacyConfigs = Array.isArray(parsedLegacyConfigs)
              ? normalizeParserSearchConfigs(
                  parsedLegacyConfigs as ParserSearchConfig[],
                )
              : [];
          } catch {
            window.localStorage.removeItem(parserSearchConfigsStorageKey);
          }
          for (const legacyConfig of legacyConfigs) {
            const filters = parserSearchFiltersFromForm(legacyConfig.form);
            const alreadyImported = serverConfigs.some((serverConfig) => {
              if (serverConfig.name !== legacyConfig.name) return false;
              return (
                JSON.stringify(
                  parserSearchFiltersFromForm(
                    parserSearchConfigFromApi(serverConfig).form,
                  ),
                ) === JSON.stringify(filters)
              );
            });
            if (alreadyImported) continue;

            const importResponse = await fetch(
              `${apiBaseUrl}/job-search/configs`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  name: legacyConfig.name,
                  filters,
                }),
              },
            );
            if (!importResponse.ok) {
              throw new Error(
                await readApiErrorMessage(
                  importResponse,
                  `Could not import config: ${legacyConfig.name}`,
                ),
              );
            }
            serverConfigs.push(
              (await importResponse.json()) as JobSearchConfigPayload,
            );
          }
          window.localStorage.removeItem(parserSearchConfigsStorageKey);
        }

        if (!isMounted) return;
        setParserSearchConfigs(serverConfigs.map(parserSearchConfigFromApi));
      } catch (error) {
        if (!isMounted) return;
        setParserSearchStatus("error");
        setParserSearchMessage(
          error instanceof Error
            ? error.message
            : "Search configs could not be loaded",
        );
      }
    }

    void loadParserSearchConfigs();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    try {
      const rawSavedJobIds = window.localStorage.getItem(savedJobIdsStorageKey);
      setSavedJobs(normalizeStoredJobIds(rawSavedJobIds ? JSON.parse(rawSavedJobIds) : []));
    } catch {
      window.localStorage.removeItem(savedJobIdsStorageKey);
    } finally {
      setAreSavedJobsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!areSavedJobsLoaded) return;

    window.localStorage.setItem(savedJobIdsStorageKey, JSON.stringify(savedJobs));
  }, [areSavedJobsLoaded, savedJobs]);

  useEffect(() => {
    try {
      const rawApplications = window.localStorage.getItem(applicationsStorageKey);
      const storedApplications = removeLegacyDemoApplications(
        normalizeStoredApplications(rawApplications ? JSON.parse(rawApplications) : []),
      );
      setApplications(storedApplications);
      setSelectedApplicationId((currentId) => currentId || storedApplications[0]?.id || "");
    } catch {
      window.localStorage.removeItem(applicationsStorageKey);
    } finally {
      setAreApplicationsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!areApplicationsLoaded) return;

    window.localStorage.setItem(applicationsStorageKey, JSON.stringify(applications));

    const abortController = new AbortController();

    async function saveStoredApplications() {
      try {
        const response = await fetch(`${apiBaseUrl}/applications`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            applications: applications.map((application) => ({
              id: application.id,
              data: application,
            })),
          }),
          signal: abortController.signal,
        });
        if (!response.ok) return;
        const storedApplications = (await response.json()) as Array<{
          id: string;
          data: unknown;
        }>;
        const authoritativeApplications = normalizeStoredApplications(
          storedApplications.map((application) => application.data),
        );
        if (authoritativeApplications.length === 0) return;
        setApplications((currentApplications) => {
          if (
            JSON.stringify(currentApplications)
            === JSON.stringify(authoritativeApplications)
          ) {
            return currentApplications;
          }
          return authoritativeApplications;
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }

    saveStoredApplications();

    return () => {
      abortController.abort();
    };
  }, [areApplicationsLoaded, applications]);

  useEffect(() => {
    try {
      const rawEvents = window.localStorage.getItem(applicationEventsStorageKey);
      const storedEvents = normalizeStoredApplicationEvents(rawEvents ? JSON.parse(rawEvents) : []);
      setApplicationEvents(sortApplicationEvents(storedEvents));
    } catch {
      window.localStorage.removeItem(applicationEventsStorageKey);
    } finally {
      setAreApplicationEventsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!areApplicationEventsLoaded) return;

    window.localStorage.setItem(applicationEventsStorageKey, JSON.stringify(applicationEvents));

    const abortController = new AbortController();

    async function saveStoredApplicationEvents() {
      try {
        await fetch(`${apiBaseUrl}/applications/events`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            events: applicationEvents.map((event) => ({
              id: event.id,
              application_id: event.applicationId,
              data: event,
            })),
          }),
          signal: abortController.signal,
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }

    saveStoredApplicationEvents();

    return () => {
      abortController.abort();
    };
  }, [areApplicationEventsLoaded, applicationEvents]);

  useEffect(() => {
    try {
      const rawSettings = window.localStorage.getItem(uiSettingsStorageKey);
      const storedSettings = rawSettings ? (JSON.parse(rawSettings) as Partial<UiSettings>) : {};
      setUiSettings({ ...defaultUiSettings, ...storedSettings });
    } catch {
      window.localStorage.removeItem(uiSettingsStorageKey);
    } finally {
      setAreUiSettingsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!areUiSettingsLoaded) return;

    window.localStorage.setItem(uiSettingsStorageKey, JSON.stringify(uiSettings));
  }, [areUiSettingsLoaded, uiSettings]);

  useEffect(() => {
    try {
      const rawLogs = window.localStorage.getItem(appLogsStorageKey);
      setAppLogs(normalizeStoredLogs(rawLogs ? JSON.parse(rawLogs) : []));
    } catch {
      window.localStorage.removeItem(appLogsStorageKey);
    } finally {
      setAreAppLogsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!areAppLogsLoaded) return;

    window.localStorage.setItem(appLogsStorageKey, JSON.stringify(appLogs.slice(0, maxStoredAppLogs)));
  }, [areAppLogsLoaded, appLogs]);

  useEffect(() => {
    if (!isProfileLoaded) return;

    cacheCandidateProfile(profile);
  }, [isProfileLoaded, profile]);

  useEffect(() => {
    const abortController = new AbortController();
    let locallyDeletedJobIds: string[] = [];

    try {
      const rawArchivedJobIds = window.localStorage.getItem(archivedJobIdsStorageKey);
      setArchivedJobIds(normalizeStoredJobIds(rawArchivedJobIds ? JSON.parse(rawArchivedJobIds) : []));
    } catch {
      window.localStorage.removeItem(archivedJobIdsStorageKey);
    }

    try {
      const rawDeletedJobIds = window.localStorage.getItem(deletedJobIdsStorageKey);
      locallyDeletedJobIds = normalizeStoredJobIds(rawDeletedJobIds ? JSON.parse(rawDeletedJobIds) : []);
      setDeletedJobIds(locallyDeletedJobIds);
    } catch {
      window.localStorage.removeItem(deletedJobIdsStorageKey);
    }

    try {
      const rawImportedJobs = window.localStorage.getItem(importedJobsStorageKey);
      const storedUserJobs = keepStoredUserJobs(normalizeStoredJobs(rawImportedJobs ? JSON.parse(rawImportedJobs) : []));
      if (storedUserJobs.length > 0) {
        window.localStorage.setItem(importedJobsStorageKey, JSON.stringify(storedUserJobs));
        setJobList((currentJobs) => [...storedUserJobs, ...currentJobs.filter((job) => !isUserManagedJob(job))]);
        setSelectedJobId((currentId) => currentId || storedUserJobs[0].id);
      }
    } catch {
      window.localStorage.removeItem(importedJobsStorageKey);
    }

    async function loadStoredJobs() {
      try {
        await refreshStoredJobsFromServer(abortController.signal);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }

    async function loadDismissedJobIds() {
      try {
        const response = await fetch(`${apiBaseUrl}/jobs/dismissed-ids`, {
          method: locallyDeletedJobIds.length > 0 ? "PUT" : "GET",
          headers: locallyDeletedJobIds.length > 0 ? { "Content-Type": "application/json" } : undefined,
          body: locallyDeletedJobIds.length > 0
            ? JSON.stringify({ job_ids: locallyDeletedJobIds })
            : undefined,
          cache: "no-store",
          signal: abortController.signal,
        });
        if (!response.ok) return;

        const serverIds = normalizeStoredJobIds(await response.json());
        setDeletedJobIds((currentIds) => {
          const nextIds = Array.from(new Set([...currentIds, ...serverIds]));
          window.localStorage.setItem(deletedJobIdsStorageKey, JSON.stringify(nextIds));
          return nextIds;
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }

    async function loadStoredApplications() {
      try {
        const response = await fetch(`${apiBaseUrl}/applications`, {
          cache: "no-store",
          signal: abortController.signal,
        });

        if (!response.ok) return;

        const storedApplications = (await response.json()) as Array<{ id: string; data: unknown }>;
        const loadedApplications = removeLegacyDemoApplications(
          normalizeStoredApplications(storedApplications.map((application) => application.data)),
        );
        if (loadedApplications.length === 0) return;

        setApplications(loadedApplications);
        setSelectedApplicationId((currentId) => currentId || loadedApplications[0]?.id || "");
        window.localStorage.setItem(applicationsStorageKey, JSON.stringify(loadedApplications));
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }

    async function loadStoredApplicationEvents() {
      try {
        const response = await fetch(`${apiBaseUrl}/applications/events`, {
          cache: "no-store",
          signal: abortController.signal,
        });

        if (!response.ok) return;

        const storedEvents = (await response.json()) as Array<{ id: string; data: unknown }>;
        const loadedEvents = sortApplicationEvents(normalizeStoredApplicationEvents(storedEvents.map((event) => event.data)));
        if (loadedEvents.length === 0) return;

        setApplicationEvents(loadedEvents);
        window.localStorage.setItem(applicationEventsStorageKey, JSON.stringify(loadedEvents));
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }

    async function loadProfile() {
      const storedProfile = readStoredCandidateProfile();
      if (storedProfile) {
        setProfile(storedProfile);
        setProfileDraft(storedProfile);
      }

      try {
        const response = await fetch(`${apiBaseUrl}/profile`, {
          cache: "no-store",
          signal: abortController.signal,
        });

        if (!response.ok) return;

        const loadedProfile = normalizeCandidateProfile((await response.json()) as Partial<CandidateProfile>);

        if (!hasCandidateProfileData(loadedProfile) && storedProfile) {
          setProfile(storedProfile);
          setProfileDraft(storedProfile);

          await fetch(`${apiBaseUrl}/profile`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(storedProfile),
            signal: abortController.signal,
          });
          return;
        }

        setProfile(loadedProfile);
        setProfileDraft(loadedProfile);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      } finally {
        if (!abortController.signal.aborted) {
          setIsProfileLoaded(true);
        }
      }
    }

    async function loadSettings() {
      try {
        const response = await fetch(`${apiBaseUrl}/settings`, {
          cache: "no-store",
          signal: abortController.signal,
        });

        if (!response.ok) return;

        setAppSettings({ ...defaultAppSettings, ...await response.json() as AppSettings });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }

    loadStoredJobs();
    loadDismissedJobIds();
    loadStoredApplications();
    loadStoredApplicationEvents();
    loadProfile();
    loadSettings();

    return () => {
      abortController.abort();
    };
  }, []);

  function changeView(view: View, applicationId?: string) {
    setActiveView(view);
    setWorkspaceApplicationId(view === "ApplicationWorkspace" ? applicationId ?? null : null);
    window.history.replaceState(null, "", getHashForView(view, applicationId));
  }

  function openJobFromDashboard(jobId: string) {
    setQuery("");
    setJobFilters(defaultJobFilters);
    setShowSavedJobs(false);
    setShowArchivedJobs(false);
    setSelectedJobId(jobId);
    setActiveTab("Overview");
    changeView("Jobs");
  }

  function startJobSearchFromDashboard() {
    setIsParserDialogOpen(true);
    changeView("Jobs");
  }

  function openApplicationFromDashboard(applicationId?: string) {
    if (applicationId) setSelectedApplicationId(applicationId);
    changeView("Applications");
  }

  function openAssistant(
    prompt = "",
    contextKind: AssistantLaunch["contextKind"] = "profile",
    contextId = "",
    autoSubmit = false,
  ) {
    setAssistantLaunch(prompt ? {
      id: createClientId("assistant-launch"),
      prompt,
      contextKind,
      contextId,
      autoSubmit,
    } : null);
    changeView("Assistant");
  }

  function appendAppLog(entry: Omit<AppLogEntry, "id" | "timestamp">) {
    setAppLogs((currentLogs) => [
      {
        ...entry,
        id: createClientId("log"),
        timestamp: new Date().toISOString(),
      },
      ...currentLogs,
    ].slice(0, maxStoredAppLogs));
  }

  function updateShowLogs(showLogs: boolean) {
    setUiSettings((currentSettings) => ({ ...currentSettings, showLogs }));
    appendAppLog({
      level: "info",
      area: "Settings",
      message: showLogs ? "Logs view enabled" : "Logs view disabled",
    });

    if (!showLogs && activeView === "Logs") {
      changeView("Settings");
    }
  }

  function clearAppLogs() {
    setAppLogs([]);
  }

  function markJobApplied(job: Job) {
    const application = createApplicationFromJob(job);
    const existingApplication = applications.find((item) => item.job.id === job.id);

    if (existingApplication) {
      setApplications((currentApplications) => currentApplications.map((item) =>
        item.id === existingApplication.id
          ? { ...item, job, status: "applied", appliedAt: new Date().toISOString() }
          : item,
      ));
      setSelectedApplicationId(existingApplication.id);
    } else {
      setApplications((currentApplications) => [application, ...currentApplications]);
      setSelectedApplicationId(application.id);
    }

    changeView("Applications");
  }

  function prepareJobApplication(job: Job) {
    const existingApplication = applications.find((item) => item.job.id === job.id);
    if (existingApplication) {
      updateApplicationJob(existingApplication.id, job);
      setSelectedApplicationId(existingApplication.id);
      changeView("ApplicationWorkspace", existingApplication.id);
    } else {
      const application = createApplicationFromJob(job, "draft");
      setApplications((currentApplications) => [application, ...currentApplications]);
      setSelectedApplicationId(application.id);
      changeView("ApplicationWorkspace", application.id);
    }
  }

  function openApplicationWorkspace(applicationId: string) {
    setSelectedApplicationId(applicationId);
    changeView("ApplicationWorkspace", applicationId);
  }

  function addManualApplication(draft: ManualApplicationDraft) {
    const application = createApplicationFromManualDraft(draft);

    setApplications((currentApplications) => [application, ...currentApplications]);
    setSelectedApplicationId(application.id);
    void analyzeApplicationWithAi(application);
    changeView("Applications");
  }

  function openManualJobDialog() {
    setManualJobDraft(defaultManualJobDraft);
    setIsManualJobDialogOpen(true);
  }

  function updateManualJobDraft<Field extends keyof ManualJobDraft>(
    field: Field,
    value: ManualJobDraft[Field],
  ) {
    setManualJobDraft((currentDraft) => ({ ...currentDraft, [field]: value }));
  }

  async function addManualJob() {
    if (!manualJobDraft.title.trim() || !manualJobDraft.company.trim() || !manualJobDraft.overview.trim()) {
      return;
    }

    const job = createManualJobFromDraft(manualJobDraft);
    setAiMatchErrorMessage("");
    setQuery("");
    setJobFilters(defaultJobFilters);
    setShowSavedJobs(false);
    setShowArchivedJobs(false);
    setSelectedJobId(job.id);
    setActiveTab("AI Match");
    setJobList((currentJobs) => {
      const nextJobs = mergeJobs([job], currentJobs);
      void persistUserJobs(nextJobs.filter(isUserManagedJob));
      return nextJobs;
    });
    setIsManualJobDialogOpen(false);
    setManualJobDraft(defaultManualJobDraft);
    setForceMatchingJobId(job.id);
    appendAppLog({
      level: "info",
      area: "AI Match",
      message: `Manual vacancy added; analysis started for ${job.title} at ${job.company}`,
    });

    try {
      const completed = await refreshAiMatch(job, true);
      if (completed) {
        appendAppLog({
          level: "success",
          area: "AI Match",
          message: `AI analysis completed for ${job.title} at ${job.company}`,
        });
      }
    } finally {
      setForceMatchingJobId((currentId) => (currentId === job.id ? "" : currentId));
    }
  }

  function updateApplicationJob(applicationId: string, job: Job) {
    setApplications((currentApplications) =>
      currentApplications.map((application) =>
        application.id === applicationId
          ? {
              ...application,
              job,
            }
          : application,
      ),
    );
  }

  async function analyzeApplicationWithAi(application: TrackedApplication) {
    setMatchingApplicationIds((currentIds) => Array.from(new Set([...currentIds, application.id])));
    appendAppLog({
      level: "info",
      area: "AI Match",
      message: `AI analysis started for ${application.job.title} at ${application.job.company}`,
    });

    try {
      const response = await fetch(`${apiBaseUrl}/jobs/ai-match?force=true`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jobs: [{ id: application.job.id, data: application.job }],
        }),
      });

      if (!response.ok) {
        const message = await readApiErrorMessage(response, "AI analysis failed");
        appendAppLog({
          level: "error",
          area: "AI Match",
          message,
          details: `${application.job.title} at ${application.job.company}`,
        });
        return;
      }

      const payload = (await response.json()) as Array<{ id: string; data: unknown }>;
      const matchedJob = normalizeStoredJobs(payload.map((item) => item.data)).find((job) => job.id === application.job.id);

      if (!matchedJob) {
        appendAppLog({
          level: "warning",
          area: "AI Match",
          message: "AI analysis completed without a matching job payload",
          details: `${application.job.title} at ${application.job.company}`,
        });
        return;
      }

      const authoritativeResponse = await fetch(
        `${apiBaseUrl}/applications/${encodeURIComponent(application.id)}/analysis`,
        { cache: "no-store" },
      );
      if (!authoritativeResponse.ok) {
        throw new Error(
          await readApiErrorMessage(
            authoritativeResponse,
            "Authoritative application analysis could not be loaded",
          ),
        );
      }
      const authoritativePayload = (await authoritativeResponse.json()) as {
        id: string;
        data: unknown;
      };
      const authoritativeApplication = normalizeStoredApplications([
        authoritativePayload.data,
      ])[0];
      if (!authoritativeApplication || authoritativeApplication.id !== application.id) {
        throw new Error("Authoritative application analysis returned an invalid payload");
      }
      setApplications((currentApplications) =>
        currentApplications.map((item) =>
          item.id === application.id ? authoritativeApplication : item,
        ),
      );
      appendAppLog({
        level: "success",
        area: "AI Match",
        message: `AI analysis completed for ${application.job.title} at ${application.job.company}`,
        details: `Score: ${formatMatchValue(authoritativeApplication.job)}`,
      });
    } catch (error) {
      appendAppLog({
        level: "error",
        area: "AI Match",
        message: error instanceof Error ? error.message : "AI analysis failed",
        details: `${application.job.title} at ${application.job.company}`,
      });
    } finally {
      setMatchingApplicationIds((currentIds) => currentIds.filter((id) => id !== application.id));
    }
  }

  function refreshApplicationAnalysis(applicationId: string) {
    const application = applications.find((item) => item.id === applicationId);
    if (!application) return;

    void analyzeApplicationWithAi(application);
  }

  function updateApplicationStatus(applicationId: string, status: ApplicationStatus) {
    setApplications((currentApplications) =>
      currentApplications.map((application) =>
        application.id === applicationId
          ? {
              ...application,
              status,
              appliedAt:
                status === "applied" && application.status === "draft"
                  ? new Date().toISOString()
                  : application.appliedAt,
            }
          : application,
      ),
    );
  }

  function updateApplicationNotes(applicationId: string, notes: string) {
    setApplications((currentApplications) =>
      currentApplications.map((application) =>
        application.id === applicationId
          ? {
              ...application,
              notes,
            }
          : application,
      ),
    );
  }

  function updateApplicationDocuments(applicationId: string, documents: ApplicationDocument[]) {
    setApplications((currentApplications) =>
      currentApplications.map((application) =>
        application.id === applicationId
          ? {
              ...application,
              documents,
            }
          : application,
      ),
    );
  }

  function attachGeneratedDocumentToApplication(
    applicationId: string,
    document: AssistantDocumentAttachment,
  ) {
    setApplications((currentApplications) =>
      currentApplications.map((application) => {
        if (application.id !== applicationId) return application;
        const generatedDocument: ApplicationDocument = {
          id: `artifact-${document.artifactId}`,
          artifactId: document.artifactId,
          title: document.title,
          fileName: document.fileName,
          fileSize: "",
          fileType: document.fileType,
          uploadedAt: document.uploadedAt,
          dataUrl: document.dataUrl,
        };
        const existingIndex = application.documents.findIndex(
          (item) => item.artifactId === document.artifactId,
        );
        const nextDocuments = existingIndex >= 0
          ? application.documents.map((item, index) => (
              index === existingIndex ? generatedDocument : item
            ))
          : [...application.documents, generatedDocument];
        return { ...application, documents: nextDocuments };
      }),
    );
  }

  function syncAssistantAppliedAction(result: AssistantAppliedAction) {
    if (result.resourceKind === "application") {
      const updatedApplication = normalizeStoredApplications([result.resource])[0];
      if (!updatedApplication) return;
      setApplications((currentApplications) => currentApplications.map((application) =>
        application.id === updatedApplication.id ? updatedApplication : application,
      ));
      return;
    }

    if (result.resourceKind === "event") {
      const createdEvent = normalizeStoredApplicationEvents([result.resource])[0];
      if (!createdEvent) return;
      setApplicationEvents((currentEvents) => sortApplicationEvents([
        createdEvent,
        ...currentEvents.filter((event) => event.id !== createdEvent.id),
      ]));
      return;
    }

    if (result.resourceKind === "profile") {
      const updatedProfile = normalizeCandidateProfile(result.resource as Partial<CandidateProfile>);
      setProfile(updatedProfile);
      setProfileDraft(updatedProfile);
    }
  }

  function deleteApplication(applicationId: string) {
    setApplications((currentApplications) => {
      const nextApplications = currentApplications.filter((application) => application.id !== applicationId);
      setSelectedApplicationId((currentId) => (currentId === applicationId ? nextApplications[0]?.id || "" : currentId));
      return nextApplications;
    });
    setApplicationEvents((currentEvents) => currentEvents.filter((event) => event.applicationId !== applicationId));

    void fetch(`${apiBaseUrl}/applications/${encodeURIComponent(applicationId)}`, {
      method: "DELETE",
    }).catch(() => undefined);
  }

  function saveApplicationEvent(event: ApplicationEvent) {
    const isExistingEvent = applicationEvents.some((item) => item.id === event.id);

    setApplicationEvents((currentEvents) => {
      const existingEvent = currentEvents.find((item) => item.id === event.id);
      const nextEvents = existingEvent
        ? currentEvents.map((item) => (item.id === event.id ? event : item))
        : [event, ...currentEvents];

      return sortApplicationEvents(nextEvents);
    });

    if (event.outcome === "negative") {
      updateApplicationStatus(event.applicationId, "rejected");
    }

    if (isExistingEvent) {
      void fetch(`${apiBaseUrl}/applications/events/${encodeURIComponent(event.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: event.id,
          application_id: event.applicationId,
          data: event,
        }),
      }).catch(() => undefined);
    }
  }

  function deleteApplicationEvent(eventId: string) {
    setApplicationEvents((currentEvents) => currentEvents.filter((event) => event.id !== eventId));

    void fetch(`${apiBaseUrl}/applications/events/${encodeURIComponent(eventId)}`, {
      method: "DELETE",
    }).catch(() => undefined);
  }

  function toggleSaved(jobId: string) {
    setSavedJobs((current) => (current.includes(jobId) ? current.filter((id) => id !== jobId) : [...current, jobId]));
  }

  function persistArchivedJobIds(jobIds: string[]) {
    window.localStorage.setItem(archivedJobIdsStorageKey, JSON.stringify(jobIds));
  }

  function persistDeletedJobIds(jobIds: string[]) {
    window.localStorage.setItem(deletedJobIdsStorageKey, JSON.stringify(jobIds));
  }

  function updateJobArchiveState(job: Job, archived: boolean) {
    const archivedAt = archived ? new Date().toISOString() : undefined;

    setArchivedJobIds((currentIds) => {
      const nextIds = archived
        ? Array.from(new Set([...currentIds, job.id]))
        : currentIds.filter((id) => id !== job.id);
      persistArchivedJobIds(nextIds);
      return nextIds;
    });

    setJobList((currentJobs) => {
      const nextJobs = currentJobs.map((item) =>
        item.id === job.id
          ? {
              ...item,
              archived,
              archivedAt,
            }
          : item,
      );
      void persistUserJobs(nextJobs.filter(isUserManagedJob));
      return nextJobs;
    });

    setSelectedJobId("");
  }

  function deleteJob(job: Job) {
    const existingApplication = applications.find((application) => application.job.id === job.id);
    const shouldDelete = window.confirm(
      existingApplication
        ? `Delete ${job.title} at ${job.company} from Jobs? The application record will stay in Applications.`
        : `Delete ${job.title} at ${job.company}?`,
    );

    if (!shouldDelete) return;

    setDeletedJobIds((currentIds) => {
      const nextIds = Array.from(new Set([...currentIds, job.id]));
      persistDeletedJobIds(nextIds);
      return nextIds;
    });
    setArchivedJobIds((currentIds) => {
      const nextIds = currentIds.filter((id) => id !== job.id);
      persistArchivedJobIds(nextIds);
      return nextIds;
    });
    setSavedJobs((currentIds) => currentIds.filter((id) => id !== job.id));

    setJobList((currentJobs) => {
      const nextJobs = currentJobs.filter((item) => item.id !== job.id);
      void persistUserJobs(nextJobs.filter(isUserManagedJob));
      return nextJobs;
    });
    setSelectedJobId("");

    void fetch(`${apiBaseUrl}/jobs/${encodeURIComponent(job.id)}`, {
      method: "DELETE",
    }).catch(() => undefined);
  }

  function updateJobFilter(filter: JobFilterKey, value: string) {
    setJobFilters((current) => ({ ...current, [filter]: value }));
    setSelectedJobId("");
    setActiveTab("Overview");
  }

  function updateParserSearchForm<Field extends keyof typeof parserSearchForm>(
    field: Field,
    value: (typeof parserSearchForm)[Field],
  ) {
    setParserSearchForm((current) => ({ ...current, [field]: value }));
    setParserSearchStatus("idle");
    setParserSearchMessage("");
  }

  function toggleParser(parser: ParserId) {
    setParserSearchForm((current) => {
      const isSelected = current.parsers.includes(parser);
      if (isSelected && current.parsers.length === 1) return current;
      return {
        ...current,
        parsers: isSelected
          ? current.parsers.filter((selectedParser) => selectedParser !== parser)
          : [...current.parsers, parser],
      };
    });
    setParserSearchStatus("idle");
    setParserSearchMessage("");
  }

  async function saveAppSettings(apiKey = brightDataApiKeyDraft) {
    setSettingsSaveStatus("loading");
    setSettingsSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brightdata_api_key: apiKey }),
      });
      const savedSettings = (await response.json()) as AppSettings & { detail?: string };

      if (!response.ok) {
        throw new Error(savedSettings.detail ?? "Settings save failed");
      }

      setAppSettings(savedSettings);
      setBrightDataApiKeyDraft("");
      setSettingsSaveStatus("ready");
      setSettingsSaveMessage(savedSettings.has_brightdata_api_key ? "Bright Data API key saved" : "Bright Data API key cleared");
    } catch (error) {
      setSettingsSaveStatus("error");
      setSettingsSaveMessage(error instanceof Error ? error.message : "Settings save failed");
    }
  }

  async function saveAiSettings(update: AppSettingsUpdate) {
    setAiSettingsSaveStatus("loading");
    setAiSettingsSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      });
      const savedSettings = (await response.json()) as AppSettings & { detail?: string };

      if (!response.ok) {
        throw new Error(savedSettings.detail ?? "AI settings save failed");
      }

      setAppSettings({ ...defaultAppSettings, ...savedSettings });
      setAiSettingsSaveStatus("ready");
      setAiSettingsSaveMessage("AI backend settings saved and activated");
    } catch (error) {
      setAiSettingsSaveStatus("error");
      setAiSettingsSaveMessage(error instanceof Error ? error.message : "AI settings save failed");
    }
  }

  async function saveParserSearchConfig() {
    const configName = parserSearchForm.searchName.trim();
    if (!configName) {
      setParserSearchStatus("error");
      setParserSearchMessage("Enter a config name before saving");
      return;
    }

    const formToSave = { ...parserSearchForm, searchName: configName };
    const isUpdate = Boolean(selectedParserSearchConfigId);
    setParserSearchStatus("loading");
    setParserSearchMessage(
      `${isUpdate ? "Updating" : "Saving"} config: ${configName}`,
    );

    try {
      let currentFilters =
        parserSearchConfigs.find(
          (config) => config.id === selectedParserSearchConfigId,
        )?.filters ?? {};
      if (isUpdate) {
        const currentResponse = await fetch(
          `${apiBaseUrl}/job-search/configs/${encodeURIComponent(
            selectedParserSearchConfigId,
          )}`,
          { cache: "no-store" },
        );
        if (!currentResponse.ok) {
          throw new Error(
            await readApiErrorMessage(
              currentResponse,
              "Current search config could not be loaded",
            ),
          );
        }
        currentFilters = (
          (await currentResponse.json()) as JobSearchConfigPayload
        ).filters;
      }
      const response = await fetch(
        `${apiBaseUrl}/job-search/configs${
          isUpdate
            ? `/${encodeURIComponent(selectedParserSearchConfigId)}`
            : ""
        }`,
        {
          method: isUpdate ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: configName,
            filters: parserSearchFiltersFromForm(
              formToSave,
              currentFilters,
            ),
          }),
        },
      );
      if (!response.ok) {
        throw new Error(
          await readApiErrorMessage(response, "Search config save failed"),
        );
      }

      const savedConfig = parserSearchConfigFromApi(
        (await response.json()) as JobSearchConfigPayload,
      );
      setParserSearchConfigs((currentConfigs) =>
        currentConfigs.some((config) => config.id === savedConfig.id)
          ? currentConfigs.map((config) =>
              config.id === savedConfig.id ? savedConfig : config,
            )
          : [savedConfig, ...currentConfigs],
      );
      setSelectedParserSearchConfigId(savedConfig.id);
      setParserSearchForm(savedConfig.form);
      setParserSearchStatus("ready");
      setParserSearchMessage(`Saved config: ${configName}`);
    } catch (error) {
      setParserSearchStatus("error");
      setParserSearchMessage(
        error instanceof Error ? error.message : "Search config save failed",
      );
    }
  }

  function loadParserSearchConfig(configId: string) {
    const config = parserSearchConfigs.find((item) => item.id === configId);
    setSelectedParserSearchConfigId(configId);

    if (!config) return;

    setParserSearchForm({ ...defaultParserSearchForm, ...config.form, searchName: config.name });
    setParserSearchStatus("ready");
    setParserSearchMessage(`Loaded config: ${config.name}`);
  }

  async function deleteParserSearchConfig() {
    if (!selectedParserSearchConfigId) return;

    const deletedConfig = parserSearchConfigs.find((config) => config.id === selectedParserSearchConfigId);
    setParserSearchStatus("loading");
    setParserSearchMessage(
      deletedConfig ? `Deleting config: ${deletedConfig.name}` : "Deleting config",
    );
    try {
      const response = await fetch(
        `${apiBaseUrl}/job-search/configs/${encodeURIComponent(selectedParserSearchConfigId)}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        throw new Error(
          await readApiErrorMessage(response, "Search config delete failed"),
        );
      }
      setParserSearchConfigs((currentConfigs) =>
        currentConfigs.filter(
          (config) => config.id !== selectedParserSearchConfigId,
        ),
      );
      setSelectedParserSearchConfigId("");
      setParserSearchStatus("ready");
      setParserSearchMessage(
        deletedConfig ? `Deleted config: ${deletedConfig.name}` : "Deleted config",
      );
    } catch (error) {
      setParserSearchStatus("error");
      setParserSearchMessage(
        error instanceof Error ? error.message : "Search config delete failed",
      );
    }
  }

  function openProfileEditor() {
    setProfileDraft(profile);
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsProfileDialogOpen(true);
  }

  function openExperienceEditor(experience?: ExperienceEntry) {
    setExperienceDraft(experience ? normalizeExperienceEntry(experience) : { ...defaultExperienceDraft, id: createClientId("experience") });
    setIsExperienceEditMode(Boolean(experience));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsExperienceDialogOpen(true);
  }

  function openEducationEditor(education?: EducationEntry) {
    setEducationDraft(education ? normalizeEducationEntry(education) : { ...defaultEducationDraft, id: createClientId("education") });
    setIsEducationEditMode(Boolean(education));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsEducationDialogOpen(true);
  }

  function openDocumentEditor(document?: DocumentEntry) {
    setDocumentDraft(document ? normalizeDocumentEntry(document) : { ...defaultDocumentDraft, id: createClientId("document") });
    setIsDocumentEditMode(Boolean(document));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsDocumentDialogOpen(true);
  }

  function openPreferencesEditor() {
    setPreferencesDraft(parseJobPreferences(profile.job_preferences));
    setPreferenceInputs(defaultPreferenceInputs);
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsPreferencesDialogOpen(true);
  }

  function openSkillsEditor() {
    setSkillsDraft(parseProfileLines(profile.skills));
    setSkillInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsSkillsDialogOpen(true);
  }

  function openDealbreakersEditor() {
    setDealbreakersDraft(parseProfileLines(profile.dealbreakers));
    setDealbreakerInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsDealbreakersDialogOpen(true);
  }

  function openAdditionalNotesEditor() {
    setAdditionalNotesDraft(profile.additional_notes);
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
    setIsAdditionalNotesDialogOpen(true);
  }

  function addSkillToDraft(skill: string) {
    const normalizedSkill = skill.trim();
    if (!normalizedSkill) return;

    setSkillsDraft((currentSkills) => {
      const existingSkills = new Set(currentSkills.map((item) => item.toLowerCase()));
      if (existingSkills.has(normalizedSkill.toLowerCase())) {
        return currentSkills;
      }

      return [...currentSkills, normalizedSkill];
    });
    setSkillInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function removeSkillFromDraft(skill: string) {
    setSkillsDraft((currentSkills) => currentSkills.filter((item) => item !== skill));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function addDealbreakerToDraft(dealbreaker: string) {
    const normalizedDealbreaker = dealbreaker.trim();
    if (!normalizedDealbreaker) return;

    setDealbreakersDraft((currentDealbreakers) => {
      const existingDealbreakers = new Set(currentDealbreakers.map((item) => item.toLowerCase()));
      if (existingDealbreakers.has(normalizedDealbreaker.toLowerCase())) {
        return currentDealbreakers;
      }

      return [...currentDealbreakers, normalizedDealbreaker];
    });
    setDealbreakerInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function removeDealbreakerFromDraft(dealbreaker: string) {
    setDealbreakersDraft((currentDealbreakers) => currentDealbreakers.filter((item) => item !== dealbreaker));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function clearDealbreakersDraft() {
    setDealbreakersDraft([]);
    setDealbreakerInput("");
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function updateProfileDraft<Field extends keyof CandidateProfile>(
    field: Field,
    value: CandidateProfile[Field],
  ) {
    setProfileDraft((current) => ({ ...current, [field]: value }));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function updatePreferencesDraft<Field extends keyof JobPreferences>(
    field: Field,
    value: JobPreferences[Field],
  ) {
    setPreferencesDraft((current) => {
      const noPreferenceField =
        field === "salary_min"
          ? "salary"
          : field === "work_authorization" || field === "swiss_permit_status"
            ? "work_authorization"
            : (["desired_roles", "seniority", "locations", "work_formats", "employment_types", "industries", "languages", "company_sizes", "priorities"] as string[]).includes(field)
              ? (field as PreferenceAnyField)
              : "";

      return normalizeJobPreferences({
        ...current,
        [field]: value,
        no_preference: noPreferenceField
          ? current.no_preference.filter((item) => item !== noPreferenceField)
          : current.no_preference,
      });
    });
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function updatePreferenceInput(field: PreferenceListField, value: string) {
    setPreferenceInputs((current) => ({ ...current, [field]: value }));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function addPreferenceListItem(field: PreferenceListField) {
    const values = preferenceInputs[field]
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (values.length === 0) return;

    setPreferencesDraft((current) =>
      normalizeJobPreferences({
        ...current,
        [field]: [...current[field], ...values],
        no_preference: current.no_preference.filter((item) => item !== field),
      }),
    );
    setPreferenceInputs((current) => ({ ...current, [field]: "" }));
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function removePreferenceListItem(field: PreferenceListField, value: string) {
    setPreferencesDraft((current) =>
      normalizeJobPreferences({
        ...current,
        [field]: current[field].filter((item) => item !== value),
      }),
    );
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function togglePreferenceOption<Field extends "seniority" | "work_formats" | "employment_types" | "company_sizes" | "priorities">(
    field: Field,
    value: string,
  ) {
    setPreferencesDraft((current) => {
      const existingValues = current[field];
      return normalizeJobPreferences({
        ...current,
        [field]: existingValues.includes(value)
          ? existingValues.filter((item) => item !== value)
          : [...existingValues, value],
        no_preference: current.no_preference.filter((item) => item !== field),
      });
    });
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  function setPreferenceAny(field: PreferenceAnyField) {
    setPreferencesDraft((current) => {
      const nextPreferences = normalizeJobPreferences({
        ...current,
        no_preference: current.no_preference.includes(field)
          ? current.no_preference.filter((item) => item !== field)
          : [...current.no_preference, field],
      });

      if (!nextPreferences.no_preference.includes(field)) {
        return nextPreferences;
      }

      if (field === "salary") {
        nextPreferences.salary_min = "";
      } else if (field === "work_authorization") {
        nextPreferences.work_authorization = "";
        nextPreferences.swiss_permit_status = "";
      } else {
        nextPreferences[field] = [];
      }

      return nextPreferences;
    });
    setProfileSaveStatus("idle");
    setProfileSaveMessage("");
  }

  async function saveProfile() {
    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profileDraft),
      });

      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Profile save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("Saved to database");
      setIsProfileDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Profile save failed");
    }
  }

  async function saveExperience() {
    const normalizedExperience = normalizeExperienceEntry(experienceDraft);

    if (!normalizedExperience.title || !normalizedExperience.company) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Enter role title and company");
      return;
    }

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    const experienceEntries = parseExperienceEntries(profile.experience);
    const existingExperience = experienceEntries.some((entry) => entry.id === normalizedExperience.id);
    const nextExperienceEntries = existingExperience
      ? experienceEntries.map((entry) => (entry.id === normalizedExperience.id ? normalizedExperience : entry))
      : [...experienceEntries, normalizedExperience];
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      experience: serializeExperienceEntries(nextExperienceEntries),
    });

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Experience save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsExperienceDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Experience save failed");
    }
  }

  async function saveEducation() {
    const normalizedEducation = normalizeEducationEntry(educationDraft);

    if (!normalizedEducation.institution || !normalizedEducation.credential) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Enter institution and credential");
      return;
    }

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    const educationEntries = parseEducationEntries(profile.education);
    const existingEducation = educationEntries.some((entry) => entry.id === normalizedEducation.id);
    const nextEducationEntries = existingEducation
      ? educationEntries.map((entry) => (entry.id === normalizedEducation.id ? normalizedEducation : entry))
      : [...educationEntries, normalizedEducation];
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      education: serializeEducationEntries(nextEducationEntries),
    });

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Education save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsEducationDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Education save failed");
    }
  }

  async function saveDocument() {
    const normalizedDocument = normalizeDocumentEntry(documentDraft);

    if (!normalizedDocument.title) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Enter document title");
      return;
    }

    if (!normalizedDocument.data_url || !normalizedDocument.file_name) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Attach a file");
      return;
    }

    if (normalizedDocument.category === "Cover Letter") {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Cover letters use the built-in template and cannot be added here");
      return;
    }

    if (normalizedDocument.category === "CV / Resume" && !normalizedDocument.file_name.toLowerCase().endsWith(".docx")) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("CV sources must be DOCX files");
      return;
    }

    if (normalizedDocument.category === "CV / Resume" && !normalizedDocument.language) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Select the document language");
      return;
    }

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    const documentEntries = parseDocumentEntries(profile.documents);
    const existingDocument = documentEntries.some((entry) => entry.id === normalizedDocument.id);
    const nextDocumentEntries = existingDocument
      ? documentEntries.map((entry) => (entry.id === normalizedDocument.id ? normalizedDocument : entry))
      : [...documentEntries, normalizedDocument];
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      documents: serializeDocumentEntries(nextDocumentEntries),
    });

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Document save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsDocumentDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Document save failed");
    }
  }

  async function savePreferences() {
    const normalizedPreferences = normalizeJobPreferences(preferencesDraft);
    if (
      normalizedPreferences.work_authorization === "Swiss permit" &&
      !hasProfileValue(normalizedPreferences.swiss_permit_status) &&
      !normalizedPreferences.no_preference.includes("work_authorization")
    ) {
      setProfileSaveStatus("error");
      setProfileSaveMessage("Select Swiss permit status");
      return;
    }

    const nextProfile = normalizeCandidateProfile({
      ...profile,
      job_preferences: serializeJobPreferences(normalizedPreferences),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Preferences save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsPreferencesDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Preferences save failed");
    }
  }

  async function saveSkills() {
    const normalizedSkills = mergeSkillLists([], skillsDraft);
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      skills: normalizedSkills.join("\n"),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Skills save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsSkillsDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Skills save failed");
    }
  }

  async function saveDealbreakers() {
    const normalizedDealbreakers = mergeSkillLists([], dealbreakersDraft);
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      dealbreakers: normalizedDealbreakers.join("\n"),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Dealbreakers save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsDealbreakersDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Dealbreakers save failed");
    }
  }

  async function saveAdditionalNotes() {
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      additional_notes: additionalNotesDraft.trim(),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Notes save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setIsAdditionalNotesDialogOpen(false);
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Notes save failed");
    }
  }

  async function deleteExperience(experienceId: string) {
    if (!window.confirm("Delete this experience entry?")) return;

    const nextExperienceEntries = parseExperienceEntries(profile.experience).filter((entry) => entry.id !== experienceId);
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      experience: serializeExperienceEntries(nextExperienceEntries),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Experience delete failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Experience delete failed");
      window.alert(error instanceof Error ? error.message : "Experience delete failed");
    }
  }

  async function deleteEducation(educationId: string) {
    if (!window.confirm("Delete this education entry?")) return;

    const nextEducationEntries = parseEducationEntries(profile.education).filter((entry) => entry.id !== educationId);
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      education: serializeEducationEntries(nextEducationEntries),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Education delete failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Education delete failed");
      window.alert(error instanceof Error ? error.message : "Education delete failed");
    }
  }

  async function deleteDocument(documentId: string) {
    if (!window.confirm("Delete this supporting document?")) return;

    const nextDocumentEntries = parseDocumentEntries(profile.documents).filter((entry) => entry.id !== documentId);
    const nextProfile = normalizeCandidateProfile({
      ...profile,
      documents: serializeDocumentEntries(nextDocumentEntries),
    });

    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await response.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!response.ok) {
        throw new Error(savedProfile.detail ?? "Document delete failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
    } catch (error) {
      setProfileSaveStatus("error");
      setProfileSaveMessage(error instanceof Error ? error.message : "Document delete failed");
      window.alert(error instanceof Error ? error.message : "Document delete failed");
    }
  }

  async function importExperienceFromCv() {
    if (!profile.resume_data_url || !profile.resume_file_name) {
      setExperienceImportMessage("Attach a resume first");
      window.alert("Attach a resume before importing experience.");
      return;
    }

    setIsExperienceImporting(true);
    setExperienceImportMessage("");
    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const importResponse = await fetch(`${apiBaseUrl}/profile/import-experience-from-resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_file_name: profile.resume_file_name,
          resume_data_url: profile.resume_data_url,
        }),
      });
      const importResult = (await importResponse.json()) as ResumeExperienceImportResponse;

      if (!importResponse.ok) {
        throw new Error(importResult.detail ?? "Experience import failed");
      }

      const importedEntries = (importResult.experience ?? []).map((entry) =>
        normalizeExperienceEntry({
          ...entry,
          id: entry.id || createClientId("cv-experience"),
        }),
      );

      if (importedEntries.length === 0) {
        setProfileSaveStatus("ready");
        setExperienceImportMessage("AI found no experience entries in the attached CV");
        return;
      }

      const currentEntries = parseExperienceEntries(profile.experience);
      const mergedEntries = mergeExperienceEntries(currentEntries, importedEntries);
      const addedCount = mergedEntries.length - currentEntries.length;

      if (addedCount === 0) {
        setProfileSaveStatus("ready");
        setExperienceImportMessage("No new experience entries found in the attached CV");
        return;
      }

      const nextProfile = normalizeCandidateProfile({
        ...profile,
        experience: serializeExperienceEntries(mergedEntries),
      });
      const saveResponse = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await saveResponse.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!saveResponse.ok) {
        throw new Error(savedProfile.detail ?? "Experience import save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setExperienceImportMessage(`AI imported ${addedCount} experience entr${addedCount === 1 ? "y" : "ies"} from CV`);
    } catch {
      const message = "AI could not import experience from CV. Please try again.";
      setProfileSaveStatus("error");
      setProfileSaveMessage(message);
      setExperienceImportMessage(message);
    } finally {
      setIsExperienceImporting(false);
    }
  }

  async function importEducationFromCv() {
    if (!profile.resume_data_url || !profile.resume_file_name) {
      setEducationImportMessage("Attach a resume first");
      window.alert("Attach a resume before importing education.");
      return;
    }

    setIsEducationImporting(true);
    setEducationImportMessage("");
    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const importResponse = await fetch(`${apiBaseUrl}/profile/import-education-from-resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_file_name: profile.resume_file_name,
          resume_data_url: profile.resume_data_url,
        }),
      });
      const importResult = (await importResponse.json()) as ResumeEducationImportResponse;

      if (!importResponse.ok) {
        throw new Error(importResult.detail ?? "Education import failed");
      }

      const importedEntries = (importResult.education ?? []).map((entry) =>
        normalizeEducationEntry({
          ...entry,
          id: entry.id || createClientId("cv-education"),
        }),
      );

      if (importedEntries.length === 0) {
        setProfileSaveStatus("ready");
        setEducationImportMessage("AI found no education entries in the attached CV");
        return;
      }

      const currentEntries = parseEducationEntries(profile.education);
      const mergedEntries = mergeEducationEntries(currentEntries, importedEntries);
      const addedCount = mergedEntries.length - currentEntries.length;

      if (addedCount === 0) {
        setProfileSaveStatus("ready");
        setEducationImportMessage("No new education entries found in the attached CV");
        return;
      }

      const nextProfile = normalizeCandidateProfile({
        ...profile,
        education: serializeEducationEntries(mergedEntries),
      });
      const saveResponse = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await saveResponse.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!saveResponse.ok) {
        throw new Error(savedProfile.detail ?? "Education import save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setEducationImportMessage(`AI imported ${addedCount} education entr${addedCount === 1 ? "y" : "ies"} from CV`);
    } catch {
      const message = "AI could not import education from CV. Please try again.";
      setProfileSaveStatus("error");
      setProfileSaveMessage(message);
      setEducationImportMessage(message);
    } finally {
      setIsEducationImporting(false);
    }
  }

  async function importSkillsFromCv() {
    if (!profile.resume_data_url || !profile.resume_file_name) {
      setSkillsImportMessage("Attach a resume first");
      window.alert("Attach a resume before importing skills.");
      return;
    }

    setIsSkillsImporting(true);
    setSkillsImportMessage("");
    setProfileSaveStatus("loading");
    setProfileSaveMessage("");

    try {
      const importResponse = await fetch(`${apiBaseUrl}/profile/import-skills-from-resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_file_name: profile.resume_file_name,
          resume_data_url: profile.resume_data_url,
        }),
      });
      const importResult = (await importResponse.json()) as ResumeSkillsImportResponse;

      if (!importResponse.ok) {
        throw new Error(importResult.detail ?? "Skills import failed");
      }

      const importedSkills = importResult.skills ?? [];
      if (importedSkills.length === 0) {
        setProfileSaveStatus("ready");
        setSkillsImportMessage("AI found no skills in the attached CV");
        return;
      }

      const currentSkills = parseProfileLines(profile.skills);
      const mergedSkills = mergeSkillLists(currentSkills, importedSkills);
      const addedCount = mergedSkills.length - currentSkills.length;

      if (addedCount === 0) {
        setProfileSaveStatus("ready");
        setSkillsImportMessage("No new skills found in the attached CV");
        return;
      }

      const nextProfile = normalizeCandidateProfile({
        ...profile,
        skills: mergedSkills.join("\n"),
      });
      const saveResponse = await fetch(`${apiBaseUrl}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextProfile),
      });
      const savedProfile = (await saveResponse.json()) as Partial<CandidateProfile> & { detail?: string };

      if (!saveResponse.ok) {
        throw new Error(savedProfile.detail ?? "Skills import save failed");
      }

      const normalizedProfile = normalizeCandidateProfile(savedProfile);
      setProfile(normalizedProfile);
      setProfileDraft(normalizedProfile);
      setSkillsDraft(parseProfileLines(normalizedProfile.skills));
      setProfileSaveStatus("ready");
      setProfileSaveMessage("");
      setSkillsImportMessage(`AI added ${addedCount} new skill${addedCount === 1 ? "" : "s"} from CV`);
    } catch {
      const message = "AI could not import skills from CV. Please try again.";
      setProfileSaveStatus("error");
      setProfileSaveMessage(message);
      setSkillsImportMessage(message);
    } finally {
      setIsSkillsImporting(false);
    }
  }

  function attachDocumentFile(file: File) {
    const isGeneratedDocumentSource = documentDraft.category === "CV / Resume";
    if (isGeneratedDocumentSource && !file.name.toLowerCase().endsWith(".docx")) {
      window.alert("CV sources must be DOCX files so their design can be preserved.");
      return;
    }
    const allowedTypes = new Set([
      "application/pdf",
      "application/msword",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "image/png",
      "image/jpeg",
      "image/webp",
    ]);
    const allowedExtensions = [".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".webp"];
    const lowerFileName = file.name.toLowerCase();
    const hasAllowedExtension = allowedExtensions.some((extension) => lowerFileName.endsWith(extension));

    if (!allowedTypes.has(file.type) && !hasAllowedExtension) {
      window.alert("Upload a PDF, DOC, DOCX, PNG, JPG, or WebP file.");
      return;
    }

    if (file.size > 5_000_000) {
      window.alert("Document file must be under 5MB.");
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== "string") return;

      const titleFromFile = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
      setDocumentDraft((current) =>
        normalizeDocumentEntry({
          ...current,
          title: current.title || titleFromFile,
          language: current.language || inferDocumentLanguage(file.name, titleFromFile),
          file_name: file.name,
          file_size: formatFileSize(file.size),
          file_type: file.type || "application/octet-stream",
          uploaded_at: new Date().toISOString(),
          data_url: reader.result as string,
        }),
      );
      setProfileSaveStatus("idle");
      setProfileSaveMessage("");
    };
    reader.readAsDataURL(file);
  }

  async function persistUserJobs(userJobs: Job[]) {
    const storedUserJobs = keepStoredUserJobs(userJobs);
    window.localStorage.setItem(importedJobsStorageKey, JSON.stringify(storedUserJobs));

    try {
      await fetch(`${apiBaseUrl}/jobs`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jobs: storedUserJobs.map((job) => ({ id: job.id, data: job })),
        }),
      });
    } catch {
      // localStorage keeps imported and manually added jobs available when the API is offline.
    }
  }

  function applyAiMatchStatus(status: AiMatchJobStatus) {
    const matchedJobs = normalizeStoredJobs(status.updatedJobs.map((job) => job.data));
    if (matchedJobs.length === 0) return;

    const matchedJobsById = new Map(matchedJobs.map((job) => [job.id, job]));
    setApplications((currentApplications) => currentApplications.map((application) => {
      const matchedJob = matchedJobsById.get(application.job.id);
      return matchedJob ? { ...application, job: matchedJob } : application;
    }));

    setJobList((currentJobs) => {
      const nextJobs = mergeJobs(matchedJobs, currentJobs);
      window.localStorage.setItem(importedJobsStorageKey, JSON.stringify(keepStoredUserJobs(nextJobs.filter(isUserManagedJob))));
      return nextJobs;
    });
  }

  function reportAiMatchError(message: string, details?: string) {
    setAiMatchErrorMessage(message);
    appendAppLog({
      level: "error",
      area: "AI Match",
      message,
      details,
    });
  }

  async function refreshAiMatches(jobsToMatch: Job[], force = false, conflictRetry = false): Promise<boolean> {
    if (jobsToMatch.length === 0) return true;
    setAiMatchErrorMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/jobs/ai-match/run${force ? "?force=true" : ""}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jobs: jobsToMatch.map((job) => ({ id: job.id, data: job })),
        }),
      });

      if (response.status === 409) {
        const previousRunStatus = await pollAiMatchStatus();
        if (!previousRunStatus || conflictRetry) return false;
        return refreshAiMatches(jobsToMatch, force, true);
      }

      if (!response.ok) {
        const message = await readApiErrorMessage(response, "AI match run could not start");
        reportAiMatchError(message, `HTTP ${response.status}`);
        return false;
      }

      const startedStatus = (await response.json()) as AiMatchJobStatus;
      applyAiMatchStatus(startedStatus);
      if (startedStatus.status === "completed") return true;

      const completedStatus = await pollAiMatchStatus();
      return Boolean(completedStatus && (completedStatus.failedJobs?.length ?? 0) === 0);
    } catch (error) {
      const message = error instanceof Error ? error.message : "AI match request failed";
      reportAiMatchError(message);
      return false;
    }
  }

  function refreshAiMatch(job: Job, force = false, conflictRetry = false) {
    return refreshAiMatches([job], force, conflictRetry);
  }

  async function runBulkAiAnalysis(scope: BulkAnalysisScope) {
    const jobsToAnalyze = getBulkAnalysisCandidates(availableJobs, scope);
    if (jobsToAnalyze.length === 0 || bulkAnalysisScope) return;

    setIsAnalysisMenuOpen(false);
    setBulkAnalysisScope(scope);
    appendAppLog({
      level: "info",
      area: "AI Match",
      message: `Bulk AI analysis started for ${jobsToAnalyze.length} vacancies`,
      details: scope === "recent" ? "Vacancies added in the last 24 hours" : "Vacancies without current AI analysis",
    });

    try {
      const completed = await refreshAiMatches(jobsToAnalyze, true);
      if (completed) {
        appendAppLog({
          level: "success",
          area: "AI Match",
          message: `Bulk AI analysis completed for ${jobsToAnalyze.length} vacancies`,
        });
      }
    } finally {
      setBulkAnalysisScope(null);
    }
  }

  async function rerunAiMatch(job: Job) {
    setForceMatchingJobId(job.id);
    try {
      await refreshAiMatch(job, true);
    } finally {
      setForceMatchingJobId((currentId) => (currentId === job.id ? "" : currentId));
    }
  }

  async function saveMatchFeedback(job: Job, feedback: MatchFeedback) {
    setMatchFeedbackSavingJobId(job.id);
    try {
      const response = await fetch(`${apiBaseUrl}/jobs/${encodeURIComponent(job.id)}/match-feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback }),
      });
      if (!response.ok) return;

      const payload = (await response.json()) as { id: string; data: unknown };
      const updatedJobs = normalizeStoredJobs([payload.data]);
      if (updatedJobs.length === 0) return;

      setJobList((currentJobs) => {
        const nextJobs = mergeJobs(updatedJobs, currentJobs);
        window.localStorage.setItem(importedJobsStorageKey, JSON.stringify(keepStoredUserJobs(nextJobs.filter(isUserManagedJob))));
        return nextJobs;
      });
    } catch {
      // Feedback is useful for calibration but should not block the main workflow.
    } finally {
      setMatchFeedbackSavingJobId((currentId) => (currentId === job.id ? "" : currentId));
    }
  }

  async function pollAiMatchStatus(): Promise<AiMatchJobStatus | null> {
    for (let attempt = 0; attempt < aiMatchStatusPollMaxAttempts; attempt += 1) {
      await wait(aiMatchStatusPollDelayMs);

      const response = await fetch(`${apiBaseUrl}/jobs/ai-match/status`, {
        cache: "no-store",
      });
      if (!response.ok) {
        const message = await readApiErrorMessage(response, "AI match status check failed");
        reportAiMatchError(message, `HTTP ${response.status}`);
        return null;
      }

      const status = (await response.json()) as AiMatchJobStatus;
      applyAiMatchStatus(status);

      if (status.status === "completed") {
        const failedJobs = status.failedJobs ?? [];
        if (failedJobs.length > 0) {
          const successfulJobs = Math.max(0, status.processed - failedJobs.length);
          reportAiMatchError(
            `AI analysis completed: ${successfulJobs} succeeded, ${failedJobs.length} failed`,
            failedJobs.map((job) => `${job.id}: ${job.error}`).join("\n"),
          );
        } else {
          setAiMatchErrorMessage("");
        }
        return status;
      }
      if (status.status === "failed") {
        reportAiMatchError(status.error || "AI match run failed");
        return null;
      }
      if (status.status === "idle") {
        reportAiMatchError("AI match run stopped before completing");
        return null;
      }
    }

    reportAiMatchError("AI match status timed out before completing");
    return null;
  }

  async function runParsers() {
    const parsers = normalizeParserIds(parserSearchForm);
    const parsersLabel = getParsersLabel(parsers);
    setParserSearchStatus("loading");
    setParserSearchMessage(`Searching ${parsersLabel}...`);
    appendAppLog({
      level: "info",
      area: "Vacancy search",
      message: `${parsersLabel} vacancy search started`,
      details: [
        `Keywords: ${parserSearchForm.keywords || "Any"}`,
        `Location: ${parserSearchForm.location || parserSearchForm.country || "Any"}`,
        `Remote: ${parserSearchForm.remote}`,
        `Limit: ${parserSearchForm.resultsLimit || "10"}`,
      ].join("\n"),
    });

    try {
      const selectedConfig = parserSearchConfigs.find(
        (config) => config.id === selectedParserSearchConfigId,
      );
      const response = await fetch(`${apiBaseUrl}/job-search/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(selectedConfig
            ? { configId: selectedConfig.id }
            : {
                config: {
                  name:
                    parserSearchForm.searchName.trim() ||
                    "Manual search",
                  filters:
                    parserSearchFiltersFromForm(parserSearchForm),
                },
              }),
          sources: parsers,
          aiAnalysisEnabled: true,
        }),
      });
      if (!response.ok) {
        throw new Error(
          await readApiErrorMessage(response, "Vacancy search failed"),
        );
      }

      const run = (await response.json()) as JobSearchRunPayload;
      const refreshedJobs = await refreshStoredJobsFromServer();
      if (run.jobsAdded > 0 && refreshedJobs.length > 0) {
        setSelectedJobId(refreshedJobs[0].id);
        setActiveTab("Overview");
      }
      const failedSources = Object.keys(run.sourceErrors).map(getParserLabel);
      const finalMessage = failedSources.length
        ? `Added ${run.jobsAdded} of ${run.jobsFound} vacancies; failed: ${failedSources.join(", ")}`
        : run.jobsAdded > 0
          ? `Added ${run.jobsAdded} of ${run.jobsFound} vacancies from ${parsersLabel}`
          : run.jobsFound > 0
            ? `Found ${run.jobsFound} vacancies; all were already saved or deleted`
            : `No vacancies returned from ${parsersLabel}`;
      const message = run.warning
        ? `${finalMessage} · ${run.warning}`
        : finalMessage;

      setParserSearchStatus("ready");
      setParserSearchMessage(message);
      appendAppLog({
        level:
          failedSources.length > 0
            ? "warning"
            : run.jobsAdded > 0
              ? "success"
              : "warning",
        area: "Vacancy search",
        message,
        details:
          failedSources.length > 0
            ? Object.entries(run.sourceErrors)
                .map(([source, error]) => `${getParserLabel(source)}: ${error}`)
                .join("\n")
            : undefined,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Vacancy search failed";
      setParserSearchStatus("error");
      setParserSearchMessage(message);
      appendAppLog({
        level: "error",
        area: "Vacancy search",
        message,
      });
    }
  }

  return (
    <main className="h-screen overflow-hidden bg-background text-foreground">
      <div className="fixed inset-0 bg-[radial-gradient(circle_at_80%_0%,rgba(52,120,246,0.10),transparent_28%)]" />
      <div className="relative mx-auto flex h-full max-w-[1536px] overflow-hidden rounded-none border-border bg-[#0a0f15]/96 shadow-panel lg:rounded-[14px] lg:border">
        <AppSidebar activeView={activeView} onChangeView={changeView} profile={profile} showLogs={uiSettings.showLogs} />

        {activeView === "Dashboard" ? (
          <DashboardView
            profile={profile}
            jobs={availableJobs.filter((job) => !job.archived)}
            applications={trackedApplications}
            events={trackedApplicationEvents}
            savedJobIds={savedJobs}
            isLoading={!isProfileLoaded || !areApplicationsLoaded || !areApplicationEventsLoaded || !areSavedJobsLoaded}
            onStartSearch={startJobSearchFromDashboard}
            onOpenJobs={() => changeView("Jobs")}
            onOpenJob={openJobFromDashboard}
            onToggleSavedJob={toggleSaved}
            onOpenApplications={openApplicationFromDashboard}
            onOpenCalendar={() => changeView("Calendar")}
            onOpenAssistant={(prompt, contextKind, contextId) => openAssistant(prompt, contextKind, contextId)}
            onOpenProfile={() => changeView("Profile")}
          />
        ) : activeView === "ApplicationWorkspace" ? (
          <ApplicationWorkspace
            application={workspaceApplication}
            profile={profile}
            backLabel={workspaceApplication?.status === "draft" ? "Jobs" : "Applications"}
            onBack={() => changeView(workspaceApplication?.status === "draft" ? "Jobs" : "Applications")}
            onOpenAssistant={(prompt, applicationId) => openAssistant(prompt, "application", applicationId)}
            onDocumentAttached={attachGeneratedDocumentToApplication}
            onRefreshAnalysis={refreshApplicationAnalysis}
            isAnalysisRefreshing={Boolean(workspaceApplication && matchingApplicationIds.includes(workspaceApplication.id))}
            onMarkApplied={(applicationId) => {
              updateApplicationStatus(applicationId, "applied");
              appendAppLog({
                level: "success",
                area: "Applications",
                message: "Application marked as applied",
              });
            }}
          />
        ) : activeView === "Applications" ? (
          <ApplicationsView
            applications={trackedApplications}
            events={trackedApplicationEvents}
            matchingApplicationIds={matchingApplicationIds}
            profile={profile}
            selectedApplication={selectedApplication}
            onSelectApplication={setSelectedApplicationId}
            onOpenJobs={() => changeView("Jobs")}
            onOpenCalendar={() => changeView("Calendar")}
            onOpenAssistant={(prompt, applicationId) => openAssistant(prompt, "application", applicationId)}
            onPrepareApplication={openApplicationWorkspace}
            onAddManualApplication={addManualApplication}
            onChangeStatus={updateApplicationStatus}
            onChangeNotes={updateApplicationNotes}
            onChangeDocuments={updateApplicationDocuments}
            onDeleteApplication={deleteApplication}
            onSaveEvent={saveApplicationEvent}
            onDeleteEvent={deleteApplicationEvent}
          />
        ) : activeView === "Calendar" ? (
          <CalendarView
            applications={trackedApplications}
            events={trackedApplicationEvents}
            onOpenAssistant={(prompt, applicationId) => openAssistant(prompt, applicationId ? "application" : "profile", applicationId)}
            onSaveEvent={saveApplicationEvent}
            onDeleteEvent={deleteApplicationEvent}
          />
        ) : activeView === "Assistant" ? (
          <AssistantView
            profile={profile}
            jobs={availableJobs}
            applications={applications}
            launch={assistantLaunch}
            onLaunchHandled={() => setAssistantLaunch(null)}
            onDocumentAttached={attachGeneratedDocumentToApplication}
            onActionApplied={syncAssistantAppliedAction}
          />
        ) : activeView === "Profile" ? (
          <ProfileView
            profile={profile}
            onOpenAssistant={(prompt) => openAssistant(prompt, "profile")}
            onEditProfile={openProfileEditor}
            onAddExperience={() => openExperienceEditor()}
            onEditExperience={openExperienceEditor}
            onDeleteExperience={deleteExperience}
            onImportExperienceFromCv={importExperienceFromCv}
            isExperienceImporting={isExperienceImporting}
            experienceImportMessage={experienceImportMessage}
            onAddEducation={() => openEducationEditor()}
            onEditEducation={openEducationEditor}
            onDeleteEducation={deleteEducation}
            onImportEducationFromCv={importEducationFromCv}
            isEducationImporting={isEducationImporting}
            educationImportMessage={educationImportMessage}
            onAddDocument={() => openDocumentEditor()}
            onEditDocument={openDocumentEditor}
            onDeleteDocument={deleteDocument}
            onEditPreferences={openPreferencesEditor}
            onEditSkills={openSkillsEditor}
            onEditDealbreakers={openDealbreakersEditor}
            onEditAdditionalNotes={openAdditionalNotesEditor}
            onImportSkillsFromCv={importSkillsFromCv}
            isSkillsImporting={isSkillsImporting}
            skillsImportMessage={skillsImportMessage}
          />
        ) : activeView === "Settings" ? (
          <SettingsView
            settings={appSettings}
            showLogs={uiSettings.showLogs}
            apiKeyDraft={brightDataApiKeyDraft}
            status={settingsSaveStatus}
            message={settingsSaveMessage}
            aiStatus={aiSettingsSaveStatus}
            aiMessage={aiSettingsSaveMessage}
            onApiKeyChange={(value) => {
              setBrightDataApiKeyDraft(value);
              setSettingsSaveStatus("idle");
              setSettingsSaveMessage("");
            }}
            onClear={() => saveAppSettings("")}
            onSave={() => saveAppSettings()}
            onSaveAi={saveAiSettings}
            onShowLogsChange={updateShowLogs}
          />
        ) : activeView === "Logs" && uiSettings.showLogs ? (
          <LogsView logs={appLogs} onClear={clearAppLogs} />
        ) : (
        <section className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
        <header className="grid shrink-0 gap-2.5 xl:grid-cols-[84px_minmax(240px,440px)_1fr] 2xl:grid-cols-[140px_minmax(280px,560px)_1fr] xl:items-center">
          <h1 className="text-[24px] font-bold leading-tight tracking-normal text-white sm:text-[27px] 2xl:text-[31px]">Jobs</h1>

          <label className="flex h-10 min-w-0 items-center gap-2.5 rounded-md border border-border bg-white/[0.075] px-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] focus-within:border-accent/70 2xl:h-12 2xl:px-4">
            <Search className="h-[18px] w-[18px] shrink-0 text-muted 2xl:h-5 2xl:w-5" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search jobs..."
              className="h-full min-w-0 flex-1 bg-transparent text-[13px] font-medium text-white outline-none placeholder:text-muted 2xl:text-sm"
            />
          </label>

          <JobsToolbar
            className="xl:col-span-3"
            savedJobsCount={savedJobsCount}
            archivedJobsCount={archivedJobsCount}
            showSavedJobs={showSavedJobs}
            showArchivedJobs={showArchivedJobs}
            isAnalysisMenuOpen={isAnalysisMenuOpen}
            bulkAnalysisScope={bulkAnalysisScope}
            recentAnalysisCount={recentAnalysisJobs.length}
            missingAnalysisCount={missingAnalysisJobs.length}
            onAddVacancy={openManualJobDialog}
            onSearchVacancies={() => {
              setParserSearchStatus("idle");
              setParserSearchMessage("");
              setIsParserDialogOpen(true);
            }}
            onToggleSavedJobs={() => {
              setShowSavedJobs((current) => !current);
              setShowArchivedJobs(false);
              setSelectedJobId("");
              setActiveTab("Overview");
            }}
            onToggleArchivedJobs={() => {
              setShowArchivedJobs((current) => !current);
              setShowSavedJobs(false);
              setSelectedJobId("");
              setActiveTab("Overview");
            }}
            onAnalysisMenuOpenChange={setIsAnalysisMenuOpen}
            onRunAnalysis={(scope) => void runBulkAiAnalysis(scope)}
            onVacanciesChanged={async () => {
              await refreshStoredJobsFromServer();
            }}
          />
        </header>

        <div className="mt-3 flex shrink-0 flex-col gap-2 lg:flex-row lg:items-center lg:justify-between 2xl:mt-5 2xl:gap-3">
          <div className="flex flex-wrap gap-1.5 2xl:gap-2">
            {jobFilterControls.map((filter) => (
              <label
                key={filter.key}
                className={cn(
                  "relative inline-flex h-8 items-center rounded-md border border-transparent bg-white/[0.055] px-2.5 text-xs font-semibold text-[#d8dee8] transition hover:bg-white/[0.09] 2xl:h-10 2xl:px-4 2xl:text-sm",
                  jobFilterWidths[filter.key],
                  jobFilters[filter.key] !== "Any" && "border-accent/70 bg-accent/15 text-white",
                )}
              >
                <select
                  aria-label={filter.label}
                  value={jobFilters[filter.key]}
                  onChange={(event) => updateJobFilter(filter.key, event.target.value)}
                  className="h-full min-w-0 flex-1 appearance-none truncate bg-transparent pr-6 font-semibold outline-none"
                >
                  <option value="Any">{filter.label}</option>
                  {filter.options.map((option) => (
                    <option key={option.value} value={option.value}>
                      {filter.label}: {option.label}
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-muted 2xl:right-4 2xl:h-4 2xl:w-4" />
              </label>
            ))}
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setJobFilters(defaultJobFilters);
                setSortBy("AI Match");
                setSelectedJobId("");
                setActiveTab("Overview");
              }}
              className={cn(
                "inline-flex h-8 items-center rounded-md border border-border bg-white/[0.09] px-3 text-xs font-semibold text-[#d8dee8] transition hover:bg-white/[0.13] 2xl:h-10 2xl:px-5 2xl:text-sm",
                (query || hasActiveJobFilters(jobFilters) || sortBy !== "AI Match") && "border-accent/60 text-white",
              )}
            >
              Reset
            </button>
          </div>

          <label className="relative inline-flex h-8 w-fit min-w-[146px] items-center gap-1.5 whitespace-nowrap rounded-md bg-white/[0.045] px-2.5 text-xs font-semibold text-[#d8dee8] transition hover:bg-white/[0.08] 2xl:h-10 2xl:min-w-[184px] 2xl:gap-2 2xl:px-4 2xl:text-sm">
            <SlidersHorizontal className="h-3.5 w-3.5 text-muted 2xl:h-4 2xl:w-4" />
            <select
              aria-label="Sort jobs"
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value as JobSortBy)}
              className="h-full min-w-0 flex-1 appearance-none bg-transparent pr-6 font-semibold outline-none"
            >
              {jobSortOptions.map((option) => (
                <option key={option} value={option}>
                  Sort by: {option}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-muted 2xl:right-4 2xl:h-4 2xl:w-4" />
          </label>
        </div>

        {aiMatchErrorMessage ? (
          <div className="mt-2.5 flex shrink-0 items-start gap-2 rounded-md border border-[#d94d4d]/45 bg-[#d94d4d]/13 px-3 py-2 text-xs font-semibold text-[#ff8a8a] 2xl:mt-3 2xl:px-4 2xl:py-2.5 2xl:text-sm">
            <X className="mt-0.5 h-4 w-4 shrink-0" />
            <p className="min-w-0 flex-1">{aiMatchErrorMessage}</p>
            <button
              type="button"
              aria-label="Dismiss AI match error"
              title="Dismiss AI match error"
              onClick={() => setAiMatchErrorMessage("")}
              className="grid h-5 w-5 shrink-0 place-items-center rounded text-[#ffb0b0] transition hover:bg-white/10 hover:text-white"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : null}

        <div className="mt-2.5 grid min-h-0 flex-1 gap-3 xl:grid-cols-[330px_minmax(0,1fr)] 2xl:mt-4 2xl:grid-cols-[420px_minmax(0,1fr)] 2xl:gap-4">
          <aside className="flex min-h-0 flex-col overflow-hidden rounded-md bg-white/[0.02]">
            <p className="shrink-0 px-1 pb-3 pt-3 text-sm font-semibold text-muted 2xl:pb-4 2xl:pt-5 2xl:text-base">
              {filteredJobs.length} {showArchivedJobs ? "archived jobs" : showSavedJobs ? "saved jobs" : "jobs"} found
            </p>
            <div className="job-scroll min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1 2xl:space-y-2">
              {filteredJobs.map((job) => (
                <article
                  key={job.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    setSelectedJobId(job.id);
                    setActiveTab("Overview");
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" && event.key !== " ") return;
                    event.preventDefault();
                    setSelectedJobId(job.id);
                    setActiveTab("Overview");
                  }}
                  className={cn(
                    "w-full cursor-pointer rounded-[8px] border p-2.5 text-left transition 2xl:p-3",
                    selectedJob?.id === job.id
                      ? "border-accent bg-white/[0.055] shadow-[0_0_0_1px_rgba(255,90,0,0.12)]"
                      : "border-border/80 bg-white/[0.035] hover:border-white/[0.16] hover:bg-white/[0.055]",
                  )}
                >
                  <div className="grid grid-cols-[42px_minmax(0,1fr)_68px] gap-2 2xl:grid-cols-[48px_minmax(0,1fr)_72px] 2xl:gap-3">
                    <JobRoleIcon job={job} compact />
                    <div className="min-w-0 pt-0.5">
                      <h2 className="line-clamp-2 text-[13px] font-bold leading-tight text-white 2xl:text-base">{job.title}</h2>
                      <p className="mt-0.5 truncate text-xs font-bold text-[#aeb5c2] 2xl:text-sm">{job.company}</p>
                      <p className="mt-1 truncate text-[10px] font-semibold text-[#aeb5c2] 2xl:text-[11px]">Source: {getJobSourceLabel(job)}</p>
                    </div>
                    <div className="grid grid-cols-2 justify-items-center gap-1.5">
                      <div className="col-span-2">
                        <JobMatchRing job={job} />
                      </div>
                      <button
                        type="button"
                        aria-label={savedJobs.includes(job.id) ? "Unsave job" : "Save job"}
                        title={savedJobs.includes(job.id) ? "Unsave job" : "Save job"}
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleSaved(job.id);
                        }}
                        className={cn(
                          "grid h-7 w-7 place-items-center rounded-md border border-border bg-white/[0.025] text-muted transition hover:border-white/25 hover:bg-white/[0.07] hover:text-white 2xl:h-8 2xl:w-8",
                          savedJobs.includes(job.id) && "border-accent/60 text-accent",
                        )}
                      >
                        <Bookmark className={cn("h-3.5 w-3.5 2xl:h-4 2xl:w-4", savedJobs.includes(job.id) && "fill-accent text-accent")} />
                      </button>
                      <button
                        type="button"
                        aria-label="Rerun AI match"
                        title="Rerun AI match"
                        disabled={forceMatchingJobId === job.id}
                        onClick={(event) => {
                          event.stopPropagation();
                          void rerunAiMatch(job);
                        }}
                        className="grid h-7 w-7 place-items-center rounded-md border border-border bg-white/[0.025] text-muted transition hover:border-white/25 hover:bg-white/[0.07] hover:text-white disabled:cursor-not-allowed disabled:opacity-55 2xl:h-8 2xl:w-8"
                      >
                        <RotateCcw className={cn("h-3.5 w-3.5 2xl:h-4 2xl:w-4", forceMatchingJobId === job.id && "animate-spin")} />
                      </button>
                    </div>
                  </div>

                  <div className="mt-2 border-t border-border/80 pt-2 2xl:mt-3 2xl:pt-2.5">
                    <div className="grid gap-1.5 text-xs font-semibold text-muted sm:grid-cols-[minmax(0,1fr)_auto] 2xl:text-[13px]">
                      <p className="flex min-w-0 flex-nowrap items-center gap-x-1.5">
                        <MapPin className="h-3.5 w-3.5 shrink-0 2xl:h-4 2xl:w-4" />
                        <span className="truncate">{formatJobLocationCompact(job.location)}</span>
                        <span className="text-white/25">•</span>
                        <span className="shrink-0 capitalize">{job.type}</span>
                      </p>
                      <p className="whitespace-nowrap text-left sm:text-right">{formatJobPostedCompact(job.posted)}</p>
                    </div>
                    {job.salary !== "Not specified" && <p className="mt-1.5 hidden truncate text-xs font-semibold text-muted/90 2xl:block 2xl:text-[13px]">{job.salary}</p>}
                    {job.archived && (
                      <p className="mt-1.5 inline-flex w-fit items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[11px] font-bold text-muted">
                        <Archive className="h-3 w-3" />
                        Archived
                      </p>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </aside>

          <section className="panel job-scroll min-h-0 overflow-y-auto p-3 md:p-4 2xl:p-5">
            {selectedJob ? (
              <>
            <div className="grid gap-5 2xl:gap-7">
              <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.58fr)] min-[1500px]:grid-cols-[minmax(0,1fr)_minmax(470px,0.72fr)] 2xl:gap-7">
                <div className="flex min-w-0 items-start gap-3 2xl:gap-4">
                  <JobRoleIcon job={selectedJob} large />
                  <div className="min-w-0 pt-0.5">
                    <h2 className="text-[22px] font-bold leading-tight text-white lg:text-[20px] min-[1400px]:text-[22px] min-[1500px]:text-[24px] 2xl:text-[29px]">{selectedJob.title}</h2>
                    <p className="mt-1.5 text-sm font-semibold text-muted 2xl:mt-2 2xl:text-base">
                      {selectedJob.company} <span className="text-white/35">•</span> {selectedJob.location} <span className="text-white/35">•</span> {selectedJob.type}
                    </p>
                    <p className="mt-1 text-xs font-semibold text-[#aeb5c2] 2xl:text-sm">Source: {getJobSourceLabel(selectedJob)}</p>
                    <p className="mt-2 text-sm font-semibold text-muted 2xl:mt-3 2xl:text-base">{selectedJob.salary}</p>
                  </div>
                </div>

                <div className="grid w-full content-start gap-2.5 sm:grid-cols-2 lg:max-w-[420px] lg:justify-self-end 2xl:max-w-[460px]">
                  <Button
                    className={cn(
                      "h-10 rounded-md border border-white/[0.14] bg-white/[0.025] px-3 text-xs font-bold text-[#e3e8ef] shadow-none hover:border-white/[0.24] hover:bg-white/[0.06] hover:text-white xl:text-[13px] 2xl:h-11 2xl:text-sm",
                      selectedJobApplication && "gap-1 px-2 text-[10px] shadow-none 2xl:gap-1.5 2xl:text-xs",
                    )}
                    onClick={() => {
                      if (selectedJobApplication) {
                        deleteApplication(selectedJobApplication.id);
                      } else {
                        markJobApplied(selectedJob);
                      }
                    }}
                  >
                    {selectedJobApplication ? (
                      <X className="h-3.5 w-3.5 2xl:h-4 2xl:w-4" />
                    ) : (
                      <span className="grid h-4 w-4 shrink-0 place-items-center rounded-full border border-[#cfd6df] 2xl:h-[18px] 2xl:w-[18px]">
                        <Check className="h-2.5 w-2.5 2xl:h-3 2xl:w-3" strokeWidth={2.4} />
                      </span>
                    )}
                    {selectedJobApplication ? "Remove application" : "Mark as Applied"}
                  </Button>
                  <Button
                    variant="ghost"
                    className="h-10 rounded-md border border-[#ff6a14] bg-accent px-3 text-xs font-bold text-white shadow-[0_8px_20px_rgba(255,90,0,0.18)] hover:border-[#ff7a26] hover:bg-[#ff6a14] xl:text-[13px] 2xl:h-11 2xl:text-sm"
                    onClick={() => prepareJobApplication(selectedJob)}
                  >
                    <FileText className="h-4 w-4 2xl:h-5 2xl:w-5" />
                    {selectedJobPreparation
                      ? selectedJobPreparation.status === "draft"
                        ? "Continue preparation"
                        : "Open application"
                      : "Prepare application"}
                  </Button>
                </div>
              </div>

              <div className="h-px bg-border" />

              <div>
                <p className="mb-2 text-[10px] font-black uppercase tracking-[0.14em] text-muted 2xl:mb-3 2xl:text-xs">Ask Assistant</p>
                <div className="grid gap-2 sm:grid-cols-2 2xl:gap-3">
                  {[
                    {
                      label: hasDisplayableMatch(selectedJob)
                        ? `Why ${selectedJob.match}%?`
                        : "Why no match score?",
                      prompt: hasDisplayableMatch(selectedJob)
                        ? assistantPrompts.whyMatch(selectedJob.match)
                        : assistantPrompts.whyNoMatch,
                      icon: BarChart3,
                      autoSubmit: true,
                    },
                    {
                      label: "What to know before applying",
                      prompt: assistantPrompts.beforeApplying,
                      icon: Info,
                      autoSubmit: false,
                    },
                  ].map((action) => {
                    const Icon = action.icon;
                    return (
                      <Button
                        key={action.label}
                        type="button"
                        variant="ghost"
                        className="h-10 justify-start rounded-md border border-accent/35 bg-accent/[0.045] px-3 text-xs font-bold text-[#f2f4f8] hover:border-accent/60 hover:bg-accent/[0.10] 2xl:h-11 2xl:text-sm"
                        onClick={() =>
                          openAssistant(
                            action.prompt,
                            "job",
                            selectedJob.id,
                            action.autoSubmit,
                          )
                        }
                      >
                        <Icon className="h-4 w-4 text-accent 2xl:h-[18px] 2xl:w-[18px]" />
                        {action.label}
                        <ChevronRight className="ml-auto h-4 w-4 text-muted" />
                      </Button>
                    );
                  })}
                </div>
              </div>

              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5 2xl:gap-3">
                <Button
                  type="button"
                  variant="ghost"
                  aria-label="Force AI match rerun"
                  title="Force AI match rerun"
                  disabled={forceMatchingJobId === selectedJob.id}
                  className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#d8dee8] hover:bg-white/[0.055] disabled:cursor-not-allowed disabled:opacity-55 2xl:h-11 2xl:text-sm"
                  onClick={() => rerunAiMatch(selectedJob)}
                >
                  <RotateCcw className={cn("h-4 w-4 2xl:h-[18px] 2xl:w-[18px]", forceMatchingJobId === selectedJob.id && "animate-spin")} />
                  {forceMatchingJobId === selectedJob.id ? "Matching" : "Rerun AI"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  aria-label={isSelectedSaved ? "Unsave job" : "Save job"}
                  title={isSelectedSaved ? "Unsave job" : "Save job"}
                  className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#d8dee8] hover:bg-white/[0.055] 2xl:h-11 2xl:text-sm"
                  onClick={() => toggleSaved(selectedJob.id)}
                >
                  <Bookmark className={cn("h-4 w-4 2xl:h-[18px] 2xl:w-[18px]", isSelectedSaved && "fill-accent text-accent")} />
                  {isSelectedSaved ? "Saved" : "Save"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  aria-label="Share job"
                  title="Share job"
                  className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#d8dee8] hover:bg-white/[0.055] 2xl:h-11 2xl:text-sm"
                  onClick={() => navigator.clipboard?.writeText(`${selectedJob.title} at ${selectedJob.company}`)}
                >
                  <Share2 className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" />
                  Share
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  aria-label={selectedJob.archived ? "Restore job" : "Archive job"}
                  title={selectedJob.archived ? "Restore job" : "Archive job"}
                  className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#d8dee8] hover:bg-white/[0.055] 2xl:h-11 2xl:text-sm"
                  onClick={() => updateJobArchiveState(selectedJob, !selectedJob.archived)}
                >
                  {selectedJob.archived ? <ArchiveRestore className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" /> : <Archive className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" />}
                  {selectedJob.archived ? "Restore" : "Archive"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  aria-label="Delete job"
                  title="Delete job"
                  className="h-10 rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#ff6b6b] hover:border-[#d94d4d]/55 hover:bg-[#d94d4d]/12 2xl:h-11 2xl:text-sm"
                  onClick={() => deleteJob(selectedJob)}
                >
                  <Trash2 className="h-4 w-4 2xl:h-[18px] 2xl:w-[18px]" />
                  Delete
                </Button>
              </div>
            </div>

            <div className="mt-5 flex gap-2 overflow-x-auto border-b border-border 2xl:mt-7 2xl:gap-4">
              {tabs.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setActiveTab(tab)}
                  className={cn(
                    "relative h-10 min-w-fit px-4 text-[13px] font-bold text-muted transition hover:text-white 2xl:h-11 2xl:px-5 2xl:text-sm",
                    activeTab === tab && "text-white after:absolute after:bottom-[-1px] after:left-0 after:h-0.5 after:w-full after:bg-accent",
                  )}
                >
                  {tab}
                </button>
              ))}
            </div>

            <div className="mt-4 grid gap-3 min-[1800px]:grid-cols-[minmax(0,1.12fr)_minmax(320px,0.9fr)] 2xl:mt-5 2xl:gap-4">
              <div className="grid gap-3 2xl:gap-4">
                <JobMainPanel
                  job={selectedJob}
                  tab={activeTab}
                  analysisRef={aiMatchAnalysisRef}
                  recommendationsRef={aiMatchRecommendationsRef}
                />
                <SalaryInsights job={selectedJob} />
              </div>

              <div className="grid content-start gap-3 2xl:gap-4">
                <MatchPanel
                  job={selectedJob}
                  isSavingFeedback={matchFeedbackSavingJobId === selectedJob.id}
                  onFeedback={saveMatchFeedback}
                  onReviewFullAnalysis={() => openAiMatchSection("analysis")}
                />
                <RecommendationsPanel job={selectedJob} onViewAllRecommendations={() => openAiMatchSection("recommendations")} />
                <JobDetails job={selectedJob} />
              </div>
            </div>
              </>
            ) : (
              <div className="grid min-h-[360px] place-items-center rounded-md border border-dashed border-border bg-white/[0.018] p-6 text-center">
                <div>
                  <Archive className="mx-auto h-9 w-9 text-muted" />
                  <h2 className="mt-4 text-xl font-bold text-white">
                    {showArchivedJobs ? "No archived jobs" : showSavedJobs ? "No saved jobs" : "No jobs found"}
                  </h2>
                  <p className="mt-2 max-w-md text-sm font-medium text-muted">
                    {showArchivedJobs
                      ? "Archived vacancies will appear here after you archive them."
                      : showSavedJobs
                        ? "Saved vacancies will appear here after you click the bookmark or Save button."
                      : "Try changing the search, resetting filters, or searching for new vacancies."}
                  </p>
                </div>
              </div>
            )}
          </section>
        </div>

        {isManualJobDialogOpen && (
          <ManualJobDialog
            draft={manualJobDraft}
            onChange={updateManualJobDraft}
            onClose={() => setIsManualJobDialogOpen(false)}
            onSave={() => void addManualJob()}
          />
        )}

        {isParserDialogOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
            <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[940px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
              <div className="flex shrink-0 items-start justify-between gap-4">
                <div>
                  <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">Search vacancies</h2>
                  <p className="mt-1 text-sm font-medium text-muted">Choose one or more sources and configure search settings</p>
                </div>
                <button
                  type="button"
                  aria-label="Close parser settings"
                  onClick={() => setIsParserDialogOpen(false)}
                  className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border">
                <div className="grid min-h-0 lg:grid-cols-[334px_minmax(0,1fr)] lg:items-start">
                  <section className="border-b border-border p-4 lg:self-start lg:border-b-0 2xl:p-5">
                    <h3 className="text-sm font-bold text-white">1. Choose sources</h3>
                    <div className="mt-4 grid gap-3">
                      {([
                        { id: "linkedin", label: "LinkedIn", description: "Extract jobs from LinkedIn", mark: "in", color: "bg-[#0a66c2]" },
                        { id: "indeed", label: "Indeed", description: "Extract jobs from Indeed", mark: "i", color: "bg-[#2557a7]" },
                        { id: "jobs_ch", label: "jobs.ch", description: "Extract jobs from jobs.ch", mark: "j", color: "bg-[#e4002b]" },
                      ] as const).map((parserOption) => {
                        const isSelected = parserSearchForm.parsers.includes(parserOption.id);
                        return (
                          <button
                            key={parserOption.id}
                            type="button"
                            aria-pressed={isSelected}
                            onClick={() => toggleParser(parserOption.id)}
                            className={cn(
                              "rounded-md border bg-white/[0.035] p-3 text-left transition",
                              isSelected
                                ? "border-accent shadow-[0_0_0_1px_rgba(255,90,0,0.18)]"
                                : "border-border hover:border-white/20 hover:bg-white/[0.055]",
                            )}
                          >
                            <div className="flex items-center gap-3">
                              <div className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-md text-lg font-black text-white", parserOption.color)}>
                                {parserOption.mark}
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <h4 className="text-sm font-bold text-white">{parserOption.label}</h4>
                                  {parserOption.id === "linkedin" && (
                                    <span className="rounded bg-success/18 px-2 py-0.5 text-[11px] font-bold text-success">Recommended</span>
                                  )}
                                </div>
                                <p className="mt-1 text-xs font-medium text-muted">{parserOption.description}</p>
                              </div>
                              <span className={cn("grid h-5 w-5 shrink-0 place-items-center rounded border-2", isSelected ? "border-accent bg-accent" : "border-white/25")}>
                                {isSelected && <Check className="h-3.5 w-3.5 text-white" />}
                              </span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </section>

                  <section className="p-4 lg:border-l lg:border-border 2xl:p-5">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-sm font-bold text-white">2. Configure parser settings</h3>
                      <button
                        type="button"
                        className="inline-flex items-center gap-2 text-xs font-bold text-muted transition hover:text-white"
                        onClick={() => {
                          setParserSearchForm(defaultParserSearchForm);
                          setSelectedParserSearchConfigId("");
                          setParserSearchStatus("idle");
                          setParserSearchMessage("");
                        }}
                      >
                        <RotateCcw className="h-4 w-4" />
                        Reset to defaults
                      </button>
                    </div>

                    <div className="mt-4 grid gap-4">
                      <label className="grid gap-2">
                        <span className="text-xs font-bold text-[#d8dee8]">Job title or keywords</span>
                        <input
                          value={parserSearchForm.keywords}
                          onChange={(event) => updateParserSearchForm("keywords", event.target.value)}
                          placeholder="e.g. Product Designer, UX Designer, Design System"
                          className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                        />
                        <span className="text-xs font-medium text-muted">Use keywords to find relevant vacancies</span>
                      </label>

                      <div className="grid gap-4 md:grid-cols-2">
                        <label className="grid gap-2">
                          <span className="text-xs font-bold text-[#d8dee8]">Location</span>
                          <input
                            value={parserSearchForm.location}
                            onChange={(event) => updateParserSearchForm("location", event.target.value)}
                            placeholder="e.g. Remote, United States, Europe"
                            className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                          />
                          <span className="text-xs font-medium text-muted">Leave empty to search worldwide</span>
                        </label>

                        <label className="grid gap-2">
                          <span className="text-xs font-bold text-[#d8dee8]">Remote</span>
                          <select
                            value={parserSearchForm.remote}
                            onChange={(event) => updateParserSearchForm("remote", event.target.value)}
                            className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                          >
                            <option>Any</option>
                            <option>Remote only</option>
                            <option>Hybrid</option>
                            <option>On-site</option>
                          </select>
                          <span className="text-xs font-medium text-muted">Filter by remote work options</span>
                        </label>

                        <label className="grid gap-2">
                          <span className="text-xs font-bold text-[#d8dee8]">Experience level</span>
                          <select
                            value={parserSearchForm.experienceLevel}
                            onChange={(event) => updateParserSearchForm("experienceLevel", event.target.value)}
                            className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                          >
                            <option>Any</option>
                            <option>Entry level</option>
                            <option>Associate</option>
                            <option>Mid-Senior level</option>
                            <option>Director</option>
                          </select>
                          <span className="text-xs font-medium text-muted">Filter by experience level</span>
                        </label>

                        <label className="grid gap-2">
                          <span className="text-xs font-bold text-[#d8dee8]">Job type</span>
                          <select
                            value={parserSearchForm.jobType}
                            onChange={(event) => updateParserSearchForm("jobType", event.target.value)}
                            className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                          >
                            <option>Any</option>
                            <option>Full-time</option>
                            <option>Part-time</option>
                            <option>Contract</option>
                            <option>Internship</option>
                          </select>
                          <span className="text-xs font-medium text-muted">Full-time, Part-time, Contract, etc.</span>
                        </label>

                        <label className="grid gap-2">
                          <span className="text-xs font-bold text-[#d8dee8]">Date posted</span>
                          <select
                            value={parserSearchForm.datePosted}
                            onChange={(event) => updateParserSearchForm("datePosted", event.target.value)}
                            className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                          >
                            <option>Any time</option>
                            <option>Past 24 hours</option>
                            <option>Past week</option>
                            <option>Past month</option>
                          </select>
                          <span className="text-xs font-medium text-muted">Filter by job posting date</span>
                        </label>
                      </div>

                      <div className="rounded-md border border-border bg-white/[0.018] p-3">
                        <div className="flex items-center justify-between">
                          <h4 className="text-sm font-bold text-white">Additional settings</h4>
                          <ChevronDown className="h-4 w-4 rotate-180 text-muted" />
                        </div>
                        <div className="mt-4 grid gap-4 md:grid-cols-2">
                          <label className="grid gap-2">
                            <span className="text-xs font-bold text-[#d8dee8]">Results limit</span>
                            <input
                              type="number"
                              min="1"
                              max="1000"
                              value={parserSearchForm.resultsLimit}
                              onChange={(event) => updateParserSearchForm("resultsLimit", event.target.value)}
                              className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                            />
                            <span className="text-xs font-medium text-muted">Maximum number of vacancies to fetch (max 1000)</span>
                          </label>

                          <label className="grid gap-2">
                            <span className="text-xs font-bold text-[#d8dee8]">Country</span>
                            <select
                              value={parserSearchForm.country}
                              onChange={(event) => updateParserSearchForm("country", event.target.value)}
                              className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                            >
                              <option>Any</option>
                              <option>United States</option>
                              <option>United Kingdom</option>
                              <option>Germany</option>
                              <option>Switzerland</option>
                            </select>
                            <span className="text-xs font-medium text-muted">Filter by country</span>
                          </label>
                        </div>

                        <div className="mt-4 flex items-start gap-3">
                          <button
                            type="button"
                            aria-label="Deduplicate results"
                            onClick={() => updateParserSearchForm("deduplicate", !parserSearchForm.deduplicate)}
                            className={cn(
                              "relative mt-0.5 h-5 w-9 rounded-full transition",
                              parserSearchForm.deduplicate ? "bg-accent shadow-[0_0_14px_rgba(255,90,0,0.22)]" : "bg-white/15",
                            )}
                          >
                            <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white transition", parserSearchForm.deduplicate ? "right-0.5" : "left-0.5")} />
                          </button>
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-bold text-white">Deduplicate results</p>
                              <Info className="h-3.5 w-3.5 text-muted" />
                            </div>
                            <p className="mt-1 text-xs font-medium text-muted">Remove duplicate vacancies</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </section>
                </div>

                <section className="border-t border-border p-4 2xl:p-5">
                  <h3 className="text-sm font-bold text-white">3. Search configs</h3>
                  <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_320px]">
                    <label className="grid gap-2 md:col-span-2">
                      <span className="text-xs font-bold text-[#d8dee8]">Existing configs</span>
                      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                        <select
                          aria-label="Existing configs"
                          value={selectedParserSearchConfigId}
                          onChange={(event) => loadParserSearchConfig(event.target.value)}
                          className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-muted outline-none focus:border-accent/70"
                        >
                          <option value="">Select saved config</option>
                          {parserSearchConfigs.map((config) => (
                            <option key={config.id} value={config.id}>
                              {config.name}
                            </option>
                          ))}
                        </select>
                        <Button
                          type="button"
                          variant="ghost"
                          className="h-9 rounded-md border border-border bg-transparent px-3 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
                          disabled={!selectedParserSearchConfigId}
                          onClick={() => void deleteParserSearchConfig()}
                        >
                          <Trash2 className="h-4 w-4" />
                          Delete
                        </Button>
                      </div>
                      <span className="text-xs font-medium text-muted">Saved on the server and available to automatic searches</span>
                    </label>

                    <label className="grid gap-2">
                      <span className="text-xs font-bold text-[#d8dee8]">Config name</span>
                      <input
                        value={parserSearchForm.searchName}
                        onChange={(event) => updateParserSearchForm("searchName", event.target.value)}
                        placeholder="e.g. Product Designer Remote Jobs"
                        className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                      />
                      <span className="text-xs font-medium text-muted">Name current settings to run them again later</span>
                    </label>

                    <label className="grid gap-2">
                      <span className="text-xs font-bold text-[#d8dee8]">Save to folder</span>
                      <select
                        value={parserSearchForm.folder}
                        onChange={(event) => updateParserSearchForm("folder", event.target.value)}
                        className="h-9 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-muted outline-none focus:border-accent/70"
                      >
                        <option value="">Select folder (optional)</option>
                        <option>Design roles</option>
                        <option>Remote jobs</option>
                        <option>High match</option>
                      </select>
                    </label>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-9 rounded-md border border-accent/55 bg-accent/12 px-4 text-[13px] text-white hover:bg-accent/18"
                      onClick={() => void saveParserSearchConfig()}
                    >
                      <Save className="h-4 w-4" />
                      Save config
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-9 rounded-md border border-border bg-transparent px-4 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
                      onClick={() => {
                        setParserSearchForm(defaultParserSearchForm);
                        setSelectedParserSearchConfigId("");
                        setParserSearchStatus("idle");
                        setParserSearchMessage("");
                      }}
                    >
                      New config
                    </Button>
                  </div>
                </section>
              </div>

              <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm font-semibold text-muted">
                  Sources: <span className="text-white">{getParsersLabel(parserSearchForm.parsers)}</span>
                  {parserSearchMessage && (
                    <span className={cn("ml-2", parserSearchStatus === "error" ? "text-[#ff7a7a]" : "text-accent")}>
                      {parserSearchMessage}
                    </span>
                  )}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
                    onClick={() => setIsParserDialogOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12]"
                    disabled={parserSearchStatus === "loading"}
                    onClick={() => void runParsers()}
                  >
                    <Search className="h-4 w-4" />
                    {parserSearchStatus === "loading" ? "Searching..." : "Start search"}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </section>
      )}
      {isProfileDialogOpen && (
        <ProfileEditorDialog
          profile={profileDraft}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={updateProfileDraft}
          onClose={() => setIsProfileDialogOpen(false)}
          onSave={saveProfile}
        />
      )}
      {isExperienceDialogOpen && (
        <ExperienceEditorDialog
          experience={experienceDraft}
          isEditMode={isExperienceEditMode}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={(field, value) => {
            setExperienceDraft((current) => ({ ...current, [field]: value }));
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onClose={() => setIsExperienceDialogOpen(false)}
          onSave={saveExperience}
        />
      )}
      {isEducationDialogOpen && (
        <EducationEditorDialog
          education={educationDraft}
          isEditMode={isEducationEditMode}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={(field, value) => {
            setEducationDraft((current) => ({ ...current, [field]: value }));
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onClose={() => setIsEducationDialogOpen(false)}
          onSave={saveEducation}
        />
      )}
      {isDocumentDialogOpen && (
        <DocumentEditorDialog
          document={documentDraft}
          isEditMode={isDocumentEditMode}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={(field, value) => {
            setDocumentDraft((current) => ({ ...current, [field]: value }));
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onAttachFile={attachDocumentFile}
          onClose={() => setIsDocumentDialogOpen(false)}
          onSave={saveDocument}
        />
      )}
      {isPreferencesDialogOpen && (
        <PreferencesEditorDialog
          preferences={preferencesDraft}
          inputs={preferenceInputs}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={updatePreferencesDraft}
          onInputChange={updatePreferenceInput}
          onAddListItem={addPreferenceListItem}
          onRemoveListItem={removePreferenceListItem}
          onToggleOption={togglePreferenceOption}
          onSetAny={setPreferenceAny}
          onClose={() => setIsPreferencesDialogOpen(false)}
          onSave={savePreferences}
        />
      )}
      {isSkillsDialogOpen && (
        <SkillsEditorDialog
          skills={skillsDraft}
          skillInput={skillInput}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onSkillInputChange={(value) => {
            setSkillInput(value);
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onAddSkill={addSkillToDraft}
          onRemoveSkill={removeSkillFromDraft}
          onClose={() => setIsSkillsDialogOpen(false)}
          onSave={saveSkills}
        />
      )}
      {isDealbreakersDialogOpen && (
        <DealbreakersEditorDialog
          dealbreakers={dealbreakersDraft}
          dealbreakerInput={dealbreakerInput}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onDealbreakerInputChange={(value) => {
            setDealbreakerInput(value);
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onAddDealbreaker={addDealbreakerToDraft}
          onRemoveDealbreaker={removeDealbreakerFromDraft}
          onClearDealbreakers={clearDealbreakersDraft}
          onClose={() => setIsDealbreakersDialogOpen(false)}
          onSave={saveDealbreakers}
        />
      )}
      {isAdditionalNotesDialogOpen && (
        <AdditionalNotesEditorDialog
          notes={additionalNotesDraft}
          status={profileSaveStatus}
          message={profileSaveMessage}
          onChange={(value) => {
            setAdditionalNotesDraft(value);
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onClear={() => {
            setAdditionalNotesDraft("");
            setProfileSaveStatus("idle");
            setProfileSaveMessage("");
          }}
          onClose={() => setIsAdditionalNotesDialogOpen(false)}
          onSave={saveAdditionalNotes}
        />
      )}
      </div>
    </main>
  );
}

type CalendarMode = "month" | "week" | "agenda";

const calendarWeekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const calendarEventTheme: Record<ApplicationEventType, { border: string; dot: string; badge: string }> = {
  screening: {
    border: "border-[#a770ff]/70 bg-[#a770ff]/[0.055] hover:bg-[#a770ff]/[0.10]",
    dot: "bg-[#a770ff]",
    badge: "border-[#a770ff]/55 bg-[#a770ff]/10 text-[#c9a8ff]",
  },
  interview: {
    border: "border-accent/75 bg-accent/[0.045] hover:bg-accent/[0.09]",
    dot: "bg-accent",
    badge: "border-accent/60 bg-accent/10 text-[#ff8a45]",
  },
  assessment: {
    border: "border-[#3478f6]/75 bg-[#3478f6]/[0.055] hover:bg-[#3478f6]/[0.11]",
    dot: "bg-[#4d91ff]",
    badge: "border-[#3478f6]/60 bg-[#3478f6]/10 text-[#62a0ff]",
  },
  follow_up: {
    border: "border-white/[0.22] bg-white/[0.025] hover:bg-white/[0.055]",
    dot: "bg-[#aeb6c2]",
    badge: "border-white/[0.20] bg-white/[0.045] text-[#adb5c1]",
  },
  offer_deadline: {
    border: "border-success/65 bg-success/[0.045] hover:bg-success/[0.09]",
    dot: "bg-success",
    badge: "border-success/55 bg-success/10 text-success",
  },
};

function getCalendarDateKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function getCalendarMonthDays(month: Date) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const mondayOffset = (first.getDay() + 6) % 7;
  const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const cellCount = Math.ceil((mondayOffset + daysInMonth) / 7) * 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayOffset);

  return Array.from({ length: cellCount }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

function getCalendarWeekDays(date: Date) {
  const start = new Date(date);
  start.setDate(date.getDate() - ((date.getDay() + 6) % 7));
  start.setHours(0, 0, 0, 0);

  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    return day;
  });
}

function createCalendarDemoEvents(month: Date): ApplicationEvent[] {
  const at = (day: number, hour: number) => new Date(month.getFullYear(), month.getMonth(), day, hour, 0, 0, 0).toISOString();

  return [
    { id: "demo-assessment", applicationId: "", type: "assessment", status: "scheduled", title: "Technical Assessment", startsAt: at(8, 10), durationMinutes: 60, timezone: getLocalTimezone(), location: "Online", notes: "Assessment" },
    { id: "demo-interview-wealth", applicationId: "", type: "interview", status: "scheduled", title: "Future Wealth Group", startsAt: at(15, 13), durationMinutes: 45, timezone: getLocalTimezone(), location: "Video call", notes: "Interview" },
    { id: "demo-interview-belimo", applicationId: "", type: "interview", status: "scheduled", title: "Belimo", startsAt: at(17, 13), durationMinutes: 45, timezone: getLocalTimezone(), location: "Video call", notes: "Interview" },
    { id: "demo-follow-up", applicationId: "", type: "follow_up", status: "scheduled", title: "Follow-up", startsAt: at(21, 10), durationMinutes: 15, timezone: getLocalTimezone(), location: "", notes: "Send thank you email" },
    { id: "demo-offer", applicationId: "", type: "offer_deadline", status: "scheduled", title: "Offer", startsAt: at(23, 15), durationMinutes: 30, timezone: getLocalTimezone(), location: "", notes: "Company X" },
  ];
}

function CalendarView({
  applications,
  events,
  onOpenAssistant,
  onSaveEvent,
  onDeleteEvent,
}: {
  applications: TrackedApplication[];
  events: ApplicationEvent[];
  onOpenAssistant: (prompt: string, applicationId: string) => void;
  onSaveEvent: (event: ApplicationEvent) => void;
  onDeleteEvent: (eventId: string) => void;
}) {
  const today = useMemo(() => new Date(), []);
  const [visibleMonth, setVisibleMonth] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const [selectedDate, setSelectedDate] = useState(today);
  const [mode, setMode] = useState<CalendarMode>("month");
  const [activeType, setActiveType] = useState<ApplicationEventType | "all">("all");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [eventDraft, setEventDraft] = useState<ApplicationEventDraft | null>(null);
  const [draftApplicationId, setDraftApplicationId] = useState("");
  const demoEvents = useMemo(() => createCalendarDemoEvents(visibleMonth), [visibleMonth]);
  const displayEvents = events.length > 0 ? events : demoEvents;
  const filteredEvents = activeType === "all" ? displayEvents : displayEvents.filter((event) => event.type === activeType);
  const monthDays = getCalendarMonthDays(visibleMonth);
  const monthRowCount = monthDays.length / 7;
  const weekDays = getCalendarWeekDays(selectedDate);
  const todayKey = getCalendarDateKey(today);
  const monthLabel = visibleMonth.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const calendarEvents = filteredEvents.filter((event) => {
    const date = new Date(event.startsAt);
    return date.getFullYear() === visibleMonth.getFullYear() && date.getMonth() === visibleMonth.getMonth();
  });
  const upcomingEvents = sortApplicationEvents(
    filteredEvents.filter((event) => event.status === "scheduled" && new Date(event.startsAt).getTime() >= today.getTime()),
  ).slice(0, 3);
  const nextInterview = sortApplicationEvents(
    displayEvents.filter((event) => event.type === "interview" && event.status === "scheduled" && new Date(event.startsAt).getTime() >= today.getTime()),
  )[0] ?? null;

  function applicationForEvent(event: ApplicationEvent) {
    return applications.find((application) => application.id === event.applicationId);
  }

  function eventCompany(event: ApplicationEvent) {
    const application = applicationForEvent(event);
    if (application) return application.job.company;
    if (event.type === "assessment") return "Assessment";
    if (event.type === "follow_up") return event.notes || "Reminder";
    if (event.type === "offer_deadline") return event.notes || "Offer";
    return event.title;
  }

  function prepareForNextInterview() {
    if (!nextInterview) return;
    const application = applicationForEvent(nextInterview);
    const startsAt = new Date(nextInterview.startsAt).toLocaleString("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    });
    const prompt = [
      assistantPrompts.prepareInterview,
      `Interview: ${nextInterview.title}`,
      application ? `Role: ${application.job.title} at ${application.job.company}` : "",
      `When: ${startsAt} (${nextInterview.timezone})`,
      nextInterview.location ? `Location: ${nextInterview.location}` : "",
      nextInterview.notes ? `Notes: ${nextInterview.notes}` : "",
    ].filter(Boolean).join("\n");

    onOpenAssistant(prompt, application?.id ?? "");
  }

  function moveMonth(offset: number) {
    const next = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + offset, 1);
    setVisibleMonth(next);
    setSelectedDate(next);
  }

  function goToToday() {
    const now = new Date();
    setVisibleMonth(new Date(now.getFullYear(), now.getMonth(), 1));
    setSelectedDate(now);
  }

  function openNewEvent(date = selectedDate) {
    const start = new Date(date);
    start.setHours(10, 0, 0, 0);
    const application = applications[0];

    setDraftApplicationId(application?.id ?? "calendar-standalone");
    setEventDraft({
      type: "interview",
      status: "scheduled",
      outcome: "",
      title: application ? `${application.job.company} interview` : "New event",
      startsAt: toDateTimeLocalValue(start),
      durationMinutes: "30",
      timezone: getLocalTimezone(),
      location: "",
      notes: "",
    });
  }

  function openEvent(event: ApplicationEvent) {
    setDraftApplicationId(event.applicationId || "calendar-standalone");
    setEventDraft(createEventDraftFromEvent(event));
  }

  function updateDraft<Field extends keyof ApplicationEventDraft>(field: Field, value: ApplicationEventDraft[Field]) {
    setEventDraft((current) => current ? { ...current, [field]: value } : current);
  }

  function saveDraft() {
    if (!eventDraft?.title.trim() || !eventDraft.startsAt) return;
    onSaveEvent(createApplicationEvent(draftApplicationId || "calendar-standalone", eventDraft));
    setEventDraft(null);
  }

  function deleteDraft() {
    if (!eventDraft?.id) return;
    onDeleteEvent(eventDraft.id);
    setEventDraft(null);
  }

  function renderEventCard(event: ApplicationEvent, compact = false) {
    const theme = calendarEventTheme[event.type];
    return (
      <button
        key={event.id}
        type="button"
        onClick={(clickEvent) => {
          clickEvent.stopPropagation();
          openEvent(event);
        }}
        className={cn(
          "w-full rounded-md border text-left transition",
          compact ? "px-2 py-1.5" : "px-2.5 py-2",
          theme.border,
        )}
      >
        <p className="flex items-center gap-1.5 truncate text-[10px] font-medium text-[#afb7c3] 2xl:text-[11px]">
          <span className={cn("h-2 w-2 shrink-0 rounded-full", theme.dot)} />
          {formatApplicationEventTime(event.startsAt)}
          {!compact ? <span className="ml-auto truncate font-semibold text-[#8fa5c7]">{getApplicationEventTypeLabel(event.type).replace(" deadline", "")}</span> : null}
        </p>
        <p className={cn("truncate font-bold text-white", compact ? "mt-0.5 text-[10px] 2xl:text-[11px]" : "mt-1 text-[11px] 2xl:text-xs")}>
          {event.title}
        </p>
        {!compact ? (
          <span className={cn("mt-1.5 inline-flex rounded border px-1.5 py-0.5 text-[9px] font-bold", theme.badge)}>
            {getApplicationEventTypeLabel(event.type).replace(" deadline", "")}
          </span>
        ) : null}
      </button>
    );
  }

  return (
    <section className="relative flex h-screen min-w-0 flex-1 flex-col overflow-hidden px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="flex shrink-0 items-center justify-between gap-4">
        <h1 className="text-[24px] font-bold leading-tight tracking-normal text-white sm:text-[27px] 2xl:text-[31px]">Calendar</h1>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            disabled={!nextInterview}
            title={nextInterview ? `Prepare for ${nextInterview.title}` : "No upcoming interview"}
            onClick={prepareForNextInterview}
            className="h-10 rounded-md border border-accent/40 bg-accent/[0.055] px-3 text-[12px] font-bold text-white hover:bg-accent/[0.11] disabled:cursor-not-allowed disabled:opacity-45 2xl:h-11 2xl:px-4 2xl:text-[13px]"
          >
            <Sparkles className="h-4 w-4 text-accent" />
            <span className="hidden sm:inline">Prepare next interview</span>
            <span className="sm:hidden">Prepare</span>
          </Button>
          <Button
            onClick={() => openNewEvent()}
            className="h-10 rounded-md bg-gradient-to-r from-[#ff6b19] to-[#ff4318] px-4 text-[13px] font-bold text-white shadow-[0_12px_28px_rgba(255,90,0,0.22)] hover:from-[#ff7b2f] hover:to-[#ff542b] 2xl:h-11 2xl:px-5"
          >
            <Plus className="h-4 w-4" />
            Add event
          </Button>
        </div>
      </header>

      <div className="mt-3 flex shrink-0 flex-wrap items-center gap-2.5 2xl:mt-4">
        <button type="button" aria-label="Previous month" onClick={() => moveMonth(-1)} className="grid h-10 w-10 place-items-center rounded-md border border-border bg-white/[0.035] text-muted transition hover:bg-white/[0.07] hover:text-white">
          <ChevronLeft className="h-5 w-5" />
        </button>
        <h2 className="min-w-[118px] text-base font-bold text-white 2xl:min-w-[132px] 2xl:text-lg">{monthLabel}</h2>
        <button type="button" aria-label="Next month" onClick={() => moveMonth(1)} className="grid h-10 w-10 place-items-center rounded-md border border-border bg-white/[0.035] text-muted transition hover:bg-white/[0.07] hover:text-white">
          <ChevronRight className="h-5 w-5" />
        </button>
        <button type="button" onClick={goToToday} className="ml-1 h-10 rounded-md border border-border bg-white/[0.035] px-4 text-[12px] font-bold text-[#cbd2dc] transition hover:bg-white/[0.07] hover:text-white">Today</button>

        <div className="ml-auto flex h-10 items-center rounded-md border border-border bg-white/[0.025] p-1">
          {(["month", "week", "agenda"] as CalendarMode[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setMode(item)}
              className={cn(
                "h-8 rounded px-4 text-[11px] font-bold capitalize transition 2xl:text-xs",
                mode === item ? "border border-accent/75 bg-accent/[0.08] text-[#ff7b35]" : "text-muted hover:text-white",
              )}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="relative">
          <button type="button" onClick={() => setIsFilterOpen((open) => !open)} className={cn("flex h-10 items-center gap-2 rounded-md border px-3.5 text-[12px] font-bold transition", activeType === "all" ? "border-border bg-white/[0.025] text-[#d6dbe3]" : "border-accent/45 bg-accent/[0.07] text-accent") }>
            <SlidersHorizontal className="h-4 w-4" />
            Filter
          </button>
          {isFilterOpen ? (
            <div className="absolute right-0 top-12 z-30 w-52 rounded-lg border border-border bg-[#121820] p-2 shadow-[0_18px_50px_rgba(0,0,0,0.55)]">
              <button type="button" onClick={() => { setActiveType("all"); setIsFilterOpen(false); }} className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-xs font-semibold text-[#dce1e9] hover:bg-white/[0.06]">
                All events {activeType === "all" ? <Check className="h-4 w-4 text-accent" /> : null}
              </button>
              {applicationEventTypes.map((item) => (
                <button key={item.type} type="button" onClick={() => { setActiveType(item.type); setIsFilterOpen(false); }} className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-xs font-semibold text-[#b9c1cc] hover:bg-white/[0.06] hover:text-white">
                  {item.label} {activeType === item.type ? <Check className="h-4 w-4 text-accent" /> : null}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="mt-3 grid min-h-0 flex-1 gap-3 xl:grid-cols-[minmax(0,1fr)_290px] 2xl:mt-4 2xl:gap-4 2xl:grid-cols-[minmax(0,1fr)_318px]">
        <div className="panel min-h-0 overflow-hidden">
          {mode === "month" ? (
            <div className="grid h-full grid-cols-7" style={{ gridTemplateRows: `42px repeat(${monthRowCount}, minmax(0, 1fr))` }}>
              {calendarWeekdays.map((day) => (
                <div key={day} className="grid place-items-center border-b border-r border-border text-[10px] font-bold text-[#adb5c2] last:border-r-0 2xl:text-xs">{day}</div>
              ))}
              {monthDays.map((date, index) => {
                const dateKey = getCalendarDateKey(date);
                const dayEvents = calendarEvents.filter((event) => getCalendarDateKey(new Date(event.startsAt)) === dateKey);
                const isCurrentMonth = date.getMonth() === visibleMonth.getMonth();
                const isToday = dateKey === todayKey;

                return (
                  <div
                    key={dateKey}
                    onClick={() => { setSelectedDate(date); openNewEvent(date); }}
                    className={cn(
                      "group relative min-h-0 overflow-hidden border-b border-r border-border p-2 text-left transition hover:bg-white/[0.025] [&:nth-last-child(-n+7)]:border-b-0 [&:nth-child(7n)]:border-r-0 2xl:p-2.5",
                      !isCurrentMonth && "bg-black/[0.08] text-[#59616d]",
                      isToday && "bg-accent/[0.025] shadow-[inset_0_0_0_1px_rgba(255,90,0,0.8)]",
                    )}
                  >
                    <span className={cn("inline-grid h-5 min-w-5 place-items-center rounded-full text-[11px] font-bold 2xl:h-6 2xl:min-w-6 2xl:text-xs", isToday ? "bg-accent text-white" : isCurrentMonth ? "text-[#e6e9ee]" : "text-[#606875]")}>{date.getDate()}</span>
                    <Plus className="absolute right-2 top-2 h-3.5 w-3.5 text-muted opacity-0 transition group-hover:opacity-100" />
                    {dayEvents.length > 0 ? <div className="mt-1 space-y-1">{dayEvents.slice(0, 2).map((event) => renderEventCard(event))}</div> : null}
                    {dayEvents.length > 2 ? <p className="mt-1 text-[9px] font-bold text-muted">+{dayEvents.length - 2} more</p> : null}
                  </div>
                );
              })}
            </div>
          ) : mode === "week" ? (
            <div className="grid h-full grid-cols-7 divide-x divide-border">
              {weekDays.map((date, index) => {
                const dateKey = getCalendarDateKey(date);
                const dayEvents = filteredEvents.filter((event) => getCalendarDateKey(new Date(event.startsAt)) === dateKey);
                return (
                  <div key={dateKey} onClick={() => openNewEvent(date)} className="min-w-0 overflow-hidden p-2 text-left hover:bg-white/[0.02] 2xl:p-3">
                    <div className="border-b border-border pb-3 text-center">
                      <p className="text-[10px] font-bold uppercase tracking-wide text-muted">{calendarWeekdays[index].slice(0, 3)}</p>
                      <span className={cn("mt-1 inline-grid h-8 w-8 place-items-center rounded-full text-sm font-bold", dateKey === todayKey ? "bg-accent text-white" : "text-white")}>{date.getDate()}</span>
                    </div>
                    <div className="mt-3 space-y-2">{dayEvents.map((event) => renderEventCard(event))}</div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="h-full overflow-y-auto p-3 2xl:p-4">
              {calendarEvents.length > 0 ? sortApplicationEvents(calendarEvents).map((event) => {
                const date = new Date(event.startsAt);
                const theme = calendarEventTheme[event.type];
                return (
                  <button key={event.id} type="button" onClick={() => openEvent(event)} className="mb-2 grid w-full grid-cols-[58px_minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-border bg-white/[0.02] p-3 text-left transition hover:bg-white/[0.05]">
                    <div className="rounded-md border border-border bg-black/10 py-2 text-center"><p className="text-[9px] font-black uppercase text-muted">{date.toLocaleDateString("en-US", { month: "short" })}</p><p className="text-xl font-bold leading-none text-white">{date.getDate()}</p></div>
                    <div className="min-w-0"><p className="truncate text-sm font-bold text-white">{event.title}</p><p className="mt-1 truncate text-xs text-muted">{formatApplicationEventTime(event.startsAt)} • {eventCompany(event)}</p></div>
                    <span className={cn("rounded border px-2 py-1 text-[10px] font-bold", theme.badge)}>{getApplicationEventTypeLabel(event.type).replace(" deadline", "")}</span>
                  </button>
                );
              }) : <div className="grid h-full place-items-center text-sm text-muted">No events this month.</div>}
            </div>
          )}
        </div>

        <aside className="hidden min-h-0 h-full xl:block">
          <section className="panel h-full min-h-0 overflow-hidden p-3 2xl:p-4">
            <div className="flex items-center justify-between gap-3"><h2 className="text-sm font-bold text-white 2xl:text-base">Upcoming</h2><button type="button" onClick={() => setMode("agenda")} className="text-[10px] font-bold text-accent 2xl:text-xs">View calendar</button></div>
            <div className="mt-3 space-y-2 overflow-y-auto 2xl:mt-4">
              {upcomingEvents.length > 0 ? upcomingEvents.map((event) => {
                const date = new Date(event.startsAt);
                const theme = calendarEventTheme[event.type];
                return (
                  <button key={event.id} type="button" onClick={() => openEvent(event)} className="grid w-full grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-2 rounded-md border border-border bg-white/[0.018] p-2 text-left transition hover:bg-white/[0.05] 2xl:grid-cols-[46px_minmax(0,1fr)_auto] 2xl:p-2.5">
                    <div className={cn("rounded-md border py-1 text-center", theme.badge)}><p className="text-[8px] font-black uppercase">{date.toLocaleDateString("en-US", { month: "short" })}</p><p className="text-lg font-bold leading-none text-white">{date.getDate()}</p></div>
                    <div className="min-w-0"><p className="truncate text-[10px] font-semibold text-[#b7bfca] 2xl:text-[11px]">{formatApplicationEventTime(event.startsAt)} • {eventCompany(event)}</p><p className="mt-1 truncate text-[10px] text-muted 2xl:text-[11px]">{event.notes || getApplicationEventTypeLabel(event.type)}</p></div>
                    <span className={cn("rounded border px-1.5 py-1 text-[8px] font-bold 2xl:text-[9px]", theme.badge)}>{getApplicationEventTypeLabel(event.type).replace(" deadline", "")}</span>
                  </button>
                );
              }) : <p className="rounded-md border border-dashed border-border p-4 text-xs leading-5 text-muted">No upcoming events.</p>}
            </div>
          </section>
        </aside>
      </div>

      {eventDraft ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={(event) => { if (event.target === event.currentTarget) setEventDraft(null); }}>
          <div className="w-full max-w-[560px] rounded-xl border border-border bg-[#11171e] shadow-[0_28px_90px_rgba(0,0,0,0.65)]">
            <div className="flex items-center justify-between border-b border-border px-5 py-4"><div><p className="text-xs font-bold uppercase tracking-[0.14em] text-accent">Calendar event</p><h2 className="mt-1 text-xl font-bold text-white">{eventDraft.id ? "Edit event" : "Add event"}</h2></div><button type="button" onClick={() => setEventDraft(null)} className="grid h-9 w-9 place-items-center rounded-md text-muted hover:bg-white/[0.06] hover:text-white"><X className="h-5 w-5" /></button></div>
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <label className="sm:col-span-2"><span className="mb-1.5 block text-xs font-bold text-[#c6cdd7]">Event title</span><input value={eventDraft.title} onChange={(event) => updateDraft("title", event.target.value)} autoFocus className="h-10 w-full rounded-md border border-border bg-white/[0.035] px-3 text-sm text-white outline-none transition focus:border-accent/60" /></label>
              <label><span className="mb-1.5 block text-xs font-bold text-[#c6cdd7]">Type</span><select value={eventDraft.type} onChange={(event) => updateDraft("type", event.target.value as ApplicationEventType)} className="h-10 w-full rounded-md border border-border bg-[#171d24] px-3 text-sm text-white outline-none focus:border-accent/60">{applicationEventTypes.map((item) => <option key={item.type} value={item.type}>{item.label}</option>)}</select></label>
              <label><span className="mb-1.5 block text-xs font-bold text-[#c6cdd7]">Application</span><select value={draftApplicationId} onChange={(event) => setDraftApplicationId(event.target.value)} className="h-10 w-full rounded-md border border-border bg-[#171d24] px-3 text-sm text-white outline-none focus:border-accent/60"><option value="calendar-standalone">Personal event</option>{applications.map((application) => <option key={application.id} value={application.id}>{application.job.company} — {application.job.title}</option>)}</select></label>
              <label><span className="mb-1.5 block text-xs font-bold text-[#c6cdd7]">Date &amp; time</span><input type="datetime-local" value={eventDraft.startsAt} onChange={(event) => updateDraft("startsAt", event.target.value)} className="h-10 w-full rounded-md border border-border bg-white/[0.035] px-3 text-sm text-white outline-none focus:border-accent/60 [color-scheme:dark]" /></label>
              <label><span className="mb-1.5 block text-xs font-bold text-[#c6cdd7]">Duration</span><select value={eventDraft.durationMinutes} onChange={(event) => updateDraft("durationMinutes", event.target.value)} className="h-10 w-full rounded-md border border-border bg-[#171d24] px-3 text-sm text-white outline-none focus:border-accent/60">{[15, 30, 45, 60, 90].map((minutes) => <option key={minutes} value={minutes}>{minutes} minutes</option>)}</select></label>
              <label className="sm:col-span-2"><span className="mb-1.5 block text-xs font-bold text-[#c6cdd7]">Location or link</span><input value={eventDraft.location} onChange={(event) => updateDraft("location", event.target.value)} placeholder="Google Meet, office, phone..." className="h-10 w-full rounded-md border border-border bg-white/[0.035] px-3 text-sm text-white outline-none placeholder:text-muted focus:border-accent/60" /></label>
              <label className="sm:col-span-2"><span className="mb-1.5 block text-xs font-bold text-[#c6cdd7]">Notes</span><textarea value={eventDraft.notes} onChange={(event) => updateDraft("notes", event.target.value)} rows={3} className="w-full resize-none rounded-md border border-border bg-white/[0.035] px-3 py-2 text-sm text-white outline-none focus:border-accent/60" /></label>
            </div>
            <div className="flex items-center justify-between border-t border-border px-5 py-4">
              <div>{eventDraft.id ? <button type="button" onClick={deleteDraft} className="flex h-9 items-center gap-2 rounded-md px-3 text-xs font-bold text-[#ff7e7e] hover:bg-[#d94d4d]/10"><Trash2 className="h-4 w-4" />Delete</button> : null}</div>
              <div className="flex gap-2"><button type="button" onClick={() => setEventDraft(null)} className="h-9 rounded-md border border-border px-4 text-xs font-bold text-[#d0d6df] hover:bg-white/[0.05]">Cancel</button><button type="button" onClick={saveDraft} disabled={!eventDraft.title.trim() || !eventDraft.startsAt} className="h-9 rounded-md bg-gradient-to-r from-[#ff6b19] to-[#ff4318] px-5 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-40">Save event</button></div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ManualJobDialog({
  draft,
  onChange,
  onClose,
  onSave,
}: {
  draft: ManualJobDraft;
  onChange: <Field extends keyof ManualJobDraft>(field: Field, value: ManualJobDraft[Field]) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const canSave = Boolean(draft.title.trim() && draft.company.trim() && draft.overview.trim());

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="manual-job-dialog-title"
        className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[780px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5"
      >
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 id="manual-job-dialog-title" className="text-[22px] font-bold leading-tight text-white">
              Add vacancy
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Paste a vacancy to save it in Jobs and analyze it against your profile.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close manual vacancy"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 grid min-h-0 flex-1 gap-4 overflow-y-auto pr-1 md:grid-cols-2">
          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#d8dee8]">Role title *</span>
            <input
              autoFocus
              value={draft.title}
              onChange={(event) => onChange("title", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Senior Product Designer"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#d8dee8]">Company *</span>
            <input
              value={draft.company}
              onChange={(event) => onChange("company", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Company name"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#d8dee8]">Location</span>
            <input
              value={draft.location}
              onChange={(event) => onChange("location", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Zurich, Remote, Europe"
            />
          </label>

          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#d8dee8]">Job posting URL</span>
            <input
              type="url"
              value={draft.applyUrl}
              onChange={(event) => onChange("applyUrl", event.target.value)}
              className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="https://company.com/careers/role"
            />
          </label>

          <label className="grid gap-2 md:col-span-2">
            <span className="text-xs font-bold text-[#d8dee8]">Vacancy description *</span>
            <textarea
              value={draft.overview}
              onChange={(event) => onChange("overview", event.target.value)}
              className="min-h-[260px] resize-y rounded-md border border-border bg-[#0d131a] px-3 py-2 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Paste the full vacancy description, including responsibilities and requirements..."
            />
          </label>
        </div>

        <div className="mt-5 flex shrink-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs font-semibold text-muted">
            Role, company, and description are required. Analysis starts automatically.
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              type="button"
              className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-5 text-[13px] text-white"
              disabled={!canSave}
              onClick={onSave}
            >
              <Sparkles className="h-4 w-4" />
              Add and analyze
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ApplicationsView({
  applications,
  events,
  matchingApplicationIds,
  profile,
  selectedApplication,
  onSelectApplication,
  onOpenJobs,
  onOpenCalendar,
  onOpenAssistant,
  onPrepareApplication,
  onAddManualApplication,
  onChangeStatus,
  onChangeNotes,
  onChangeDocuments,
  onDeleteApplication,
  onSaveEvent,
  onDeleteEvent,
}: {
  applications: TrackedApplication[];
  events: ApplicationEvent[];
  matchingApplicationIds: string[];
  profile: CandidateProfile;
  selectedApplication: TrackedApplication | null;
  onSelectApplication: (applicationId: string) => void;
  onOpenJobs: () => void;
  onOpenCalendar: () => void;
  onOpenAssistant: (prompt: string, applicationId: string) => void;
  onPrepareApplication: (applicationId: string) => void;
  onAddManualApplication: (draft: ManualApplicationDraft) => void;
  onChangeStatus: (applicationId: string, status: ApplicationStatus) => void;
  onChangeNotes: (applicationId: string, notes: string) => void;
  onChangeDocuments: (applicationId: string, documents: ApplicationDocument[]) => void;
  onDeleteApplication: (applicationId: string) => void;
  onSaveEvent: (event: ApplicationEvent) => void;
  onDeleteEvent: (eventId: string) => void;
}) {
  const [applicationQuery, setApplicationQuery] = useState("");
  const [selectedStatusFilter, setSelectedStatusFilter] = useState<ApplicationStatus | "all">("all");
  const [isScheduleDialogOpen, setIsScheduleDialogOpen] = useState(false);
  const [eventDraft, setEventDraft] = useState<ApplicationEventDraft | null>(null);
  const [activeEventMenuId, setActiveEventMenuId] = useState("");
  const [isApplicationMenuOpen, setIsApplicationMenuOpen] = useState(false);
  const [isNotesDialogOpen, setIsNotesDialogOpen] = useState(false);
  const [applicationNotesDraft, setApplicationNotesDraft] = useState("");
  const [aiInfoApplicationId, setAiInfoApplicationId] = useState("");
  const [isManualApplicationDialogOpen, setIsManualApplicationDialogOpen] = useState(false);
  const [manualApplicationDraft, setManualApplicationDraft] = useState<ManualApplicationDraft>(defaultManualApplicationDraft);
  const statusCounts = applications.reduce(
    (counts, application) => ({
      ...counts,
      [application.status]: counts[application.status] + 1,
    }),
    { draft: 0, applied: 0, interview: 0, assessment: 0, offer: 0, rejected: 0 } satisfies Record<ApplicationStatus, number>,
  );
  const activeCount = statusCounts.interview + statusCounts.assessment + statusCounts.offer;
  const responseRate = applications.length > 0 ? Math.round((activeCount / applications.length) * 100) : 0;
  const statCards = [
    { label: "Total applications", value: applications.length.toString(), icon: FileText, iconClassName: "bg-white/[0.055] text-[#d8dee8]" },
    { label: "Interviews", value: statusCounts.interview.toString(), icon: CalendarDays, iconClassName: "bg-accent/16 text-accent" },
    { label: "Assessments", value: statusCounts.assessment.toString(), icon: FileText, iconClassName: "bg-[#2f80ed]/16 text-[#8cc7ff]" },
    { label: "Offers", value: statusCounts.offer.toString(), icon: BriefcaseBusiness, iconClassName: "bg-success/16 text-success" },
    { label: "Response rate", value: `${responseRate}%`, icon: Target, iconClassName: "bg-[#9f7aea]/16 text-[#c4a7ff]" },
  ];
  const normalizedApplicationQuery = applicationQuery.trim().toLowerCase();
  const filteredApplications = applications.filter((application) => {
    const matchesStatus = selectedStatusFilter === "all" || application.status === selectedStatusFilter;
    const matchesQuery =
      normalizedApplicationQuery.length === 0 ||
      [application.job.title, application.job.company, application.job.location, application.job.type, application.nextStep].some((value) =>
        value.toLowerCase().includes(normalizedApplicationQuery),
      );

    return matchesStatus && matchesQuery;
  });
  const matchingApplicationIdSet = new Set(matchingApplicationIds);
  const visibleSelectedApplication =
    selectedApplication && filteredApplications.some((application) => application.id === selectedApplication.id)
      ? selectedApplication
      : filteredApplications[0] ?? null;
  const visibleApplicationEvents = visibleSelectedApplication
    ? sortApplicationEvents(events.filter((event) => event.applicationId === visibleSelectedApplication.id))
    : [];
  const aiInfoApplication = applications.find((application) => application.id === aiInfoApplicationId) ?? null;
  const nextApplicationEvent =
    visibleApplicationEvents.find(
      (event) => event.status === "scheduled" && new Date(event.startsAt).getTime() >= Date.now(),
    ) ?? null;
  const upcomingEvents = sortApplicationEvents(
    events.filter(
      (event) =>
        filteredApplications.some((application) => application.id === event.applicationId) &&
        event.status === "scheduled" &&
        new Date(event.startsAt).getTime() >= Date.now(),
    ),
  ).slice(0, 3);
  const isEditingEvent = Boolean(eventDraft?.id);
  const timelineItems: ApplicationTimelineItem[] = visibleSelectedApplication
    ? [
        {
          label: visibleSelectedApplication.status === "draft" ? "Application created" : "Applied",
          date: formatApplicationDate(visibleSelectedApplication.appliedAt),
          state: visibleSelectedApplication.status === "draft" ? "current" : "done",
        },
        ...visibleApplicationEvents.map((event) => {
          const isNextEvent = nextApplicationEvent?.id === event.id;
          const state: ApplicationTimelineItem["state"] =
            event.status === "canceled"
              ? "canceled"
              : event.outcome === "negative"
                ? "rejected"
                : event.status === "completed"
                  ? "done"
                  : isNextEvent
                    ? "current"
                    : "future";

          return {
            label: getApplicationTimelineEventLabel(event.type),
            date: `${formatApplicationEventDate(event.startsAt)} at ${formatApplicationEventTime(event.startsAt)}`,
            state,
            event,
          };
        }),
      ]
    : [];

  function openManualApplicationDialog() {
    setManualApplicationDraft(defaultManualApplicationDraft);
    setIsManualApplicationDialogOpen(true);
  }

  function updateManualApplicationDraft<Field extends keyof ManualApplicationDraft>(
    field: Field,
    value: ManualApplicationDraft[Field],
  ) {
    setManualApplicationDraft((currentDraft) => ({ ...currentDraft, [field]: value }));
  }

  function useProfileResumeForManualApplication() {
    const resumeDocument = createProfileResumeApplicationDocument(profile);
    if (!resumeDocument) return;

    updateManualApplicationDraft("documents", [resumeDocument]);
  }

  function attachManualApplicationResume(file: File | undefined) {
    if (!file) return;

    const allowedTypes = new Set([
      "application/pdf",
      "application/msword",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]);
    const allowedExtensions = [".pdf", ".doc", ".docx"];
    const lowerFileName = file.name.toLowerCase();
    const hasAllowedExtension = allowedExtensions.some((extension) => lowerFileName.endsWith(extension));

    if (!allowedTypes.has(file.type) && !hasAllowedExtension) {
      window.alert("Upload a PDF, DOC, or DOCX resume.");
      return;
    }

    if (file.size > 5_000_000) {
      window.alert("Resume file must be under 5MB.");
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== "string") return;

      const title = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() || file.name;
      updateManualApplicationDraft("documents", [
        {
          id: createClientId("application-resume"),
          title,
          fileName: file.name,
          fileSize: formatFileSize(file.size),
          fileType: file.type || "application/octet-stream",
          uploadedAt: new Date().toISOString(),
          dataUrl: reader.result,
        },
      ]);
    };
    reader.readAsDataURL(file);
  }

  function saveManualApplication() {
    if (
      !manualApplicationDraft.title.trim() ||
      !manualApplicationDraft.company.trim() ||
      !manualApplicationDraft.location.trim() ||
      !manualApplicationDraft.applyUrl.trim() ||
      !manualApplicationDraft.overview.trim()
    ) {
      return;
    }

    onAddManualApplication(manualApplicationDraft);
    setManualApplicationDraft(defaultManualApplicationDraft);
    setIsManualApplicationDialogOpen(false);
  }

  function openApplicationAiInfo(applicationId: string) {
    setAiInfoApplicationId(applicationId);
    setIsApplicationMenuOpen(false);
  }

  function openScheduleDialog() {
    if (!visibleSelectedApplication) return;

    setEventDraft(createDefaultEventDraft(visibleSelectedApplication));
    setActiveEventMenuId("");
    setIsScheduleDialogOpen(true);
  }

  function openEditEventDialog(event: ApplicationEvent) {
    setEventDraft(createEventDraftFromEvent(event));
    setActiveEventMenuId("");
    setIsScheduleDialogOpen(true);
  }

  function updateEventDraft<Field extends keyof ApplicationEventDraft>(field: Field, value: ApplicationEventDraft[Field]) {
    setEventDraft((currentDraft) => {
      if (!currentDraft) return currentDraft;

      const nextDraft = { ...currentDraft, [field]: value };
      if (field === "status" && value !== "completed") {
        nextDraft.outcome = "";
      }

      return nextDraft;
    });
  }

  function saveEventDraft() {
    if (!visibleSelectedApplication || !eventDraft || !eventDraft.startsAt) return;

    onSaveEvent(createApplicationEvent(visibleSelectedApplication.id, eventDraft));
    setIsScheduleDialogOpen(false);
    setEventDraft(null);
  }

  function updateEvent(event: ApplicationEvent, updates: Partial<Pick<ApplicationEvent, "status" | "outcome">>) {
    onSaveEvent({
      ...event,
      ...updates,
    });
    setActiveEventMenuId("");
  }

  function deleteEvent(eventId: string) {
    onDeleteEvent(eventId);
    setActiveEventMenuId("");
  }

  function openApplicationPosting() {
    if (!visibleSelectedApplication) return;

    const postingUrl = visibleSelectedApplication.job.applyUrl || visibleSelectedApplication.job.sourceUrl;
    if (!postingUrl) return;

    window.open(postingUrl, "_blank", "noopener,noreferrer");
    setIsApplicationMenuOpen(false);
  }

  function changeApplicationStatus(status: ApplicationStatus) {
    if (!visibleSelectedApplication) return;

    onChangeStatus(visibleSelectedApplication.id, status);
    setIsApplicationMenuOpen(false);
  }

  function openNotesDialog() {
    if (!visibleSelectedApplication) return;

    setApplicationNotesDraft(getVisibleApplicationNotes(visibleSelectedApplication.notes));
    setIsApplicationMenuOpen(false);
    setIsNotesDialogOpen(true);
  }

  function saveApplicationNotes() {
    if (!visibleSelectedApplication) return;

    onChangeNotes(visibleSelectedApplication.id, applicationNotesDraft.trim());
    setIsNotesDialogOpen(false);
  }

  function deleteSelectedApplication() {
    if (!visibleSelectedApplication) return;
    const shouldDelete = window.confirm(`Delete application for ${visibleSelectedApplication.job.title} at ${visibleSelectedApplication.job.company}?`);
    if (!shouldDelete) return;

    onDeleteApplication(visibleSelectedApplication.id);
    setIsApplicationMenuOpen(false);
  }

  function getApplicationDocumentBadge(document: ApplicationDocument) {
    const extension = document.fileName.split(".").pop()?.trim().toUpperCase();
    if (extension && extension.length <= 5) return extension;
    if (document.fileType.includes("pdf")) return "PDF";
    if (document.fileType.includes("word")) return "DOC";
    if (document.fileType.includes("image")) return "IMG";
    return "FILE";
  }

  function attachApplicationDocument(file: File | undefined) {
    if (!file || !visibleSelectedApplication) return;

    const allowedTypes = new Set([
      "application/pdf",
      "application/msword",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "image/png",
      "image/jpeg",
      "image/webp",
    ]);
    const allowedExtensions = [".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".webp"];
    const lowerFileName = file.name.toLowerCase();
    const hasAllowedExtension = allowedExtensions.some((extension) => lowerFileName.endsWith(extension));

    if (!allowedTypes.has(file.type) && !hasAllowedExtension) {
      window.alert("Upload a PDF, DOC, DOCX, PNG, JPG, or WebP file.");
      return;
    }

    if (file.size > 5_000_000) {
      window.alert("Document file must be under 5MB.");
      return;
    }

    const application = visibleSelectedApplication;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== "string") return;

      const title = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() || file.name;
      const document: ApplicationDocument = {
        id: createClientId("application-document"),
        title,
        fileName: file.name,
        fileSize: formatFileSize(file.size),
        fileType: file.type || "application/octet-stream",
        uploadedAt: new Date().toISOString(),
        dataUrl: reader.result,
      };

      onChangeDocuments(application.id, [...application.documents, document]);
    };
    reader.readAsDataURL(file);
  }

  function deleteApplicationDocument(documentId: string) {
    if (!visibleSelectedApplication) return;

    const document = visibleSelectedApplication.documents.find((item) => item.id === documentId);
    if (document?.artifactId) {
      void fetch(
        `${apiBaseUrl}/documents/${encodeURIComponent(document.artifactId)}/attachments/${encodeURIComponent(visibleSelectedApplication.id)}`,
        { method: "DELETE" },
      );
    }

    onChangeDocuments(
      visibleSelectedApplication.id,
      visibleSelectedApplication.documents.filter((document) => document.id !== documentId),
    );
  }

  return (
    <section className="job-scroll flex h-screen min-w-0 flex-1 flex-col overflow-y-auto px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-3 grid shrink-0 gap-3 xl:grid-cols-[190px_minmax(0,1fr)] xl:items-center 2xl:mb-4 2xl:grid-cols-[minmax(280px,430px)_minmax(0,1fr)]">
        <div>
          <h1 className="text-[24px] font-bold leading-tight tracking-normal text-white 2xl:text-[31px]">Applications</h1>
          <p className="mt-1 text-[12px] text-muted 2xl:mt-1.5 2xl:text-base">Track submitted roles and next steps</p>
        </div>

        <div className="grid gap-2 md:grid-cols-[minmax(260px,1fr)_auto] xl:grid-cols-[minmax(210px,250px)_minmax(0,1fr)_auto] 2xl:gap-3 2xl:grid-cols-[minmax(320px,420px)_minmax(0,1fr)_auto]">
          <label className="flex h-10 min-w-0 items-center gap-2.5 rounded-md border border-border bg-white/[0.045] px-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] focus-within:border-accent/70 2xl:h-12 2xl:gap-3 2xl:px-4">
            <Search className="h-[17px] w-[17px] shrink-0 text-muted 2xl:h-5 2xl:w-5" />
            <input
              value={applicationQuery}
              onChange={(event) => setApplicationQuery(event.target.value)}
              placeholder="Search applications..."
              className="h-full min-w-0 flex-1 bg-transparent text-xs font-semibold text-white outline-none placeholder:text-muted 2xl:text-sm"
            />
          </label>

          <div className="flex h-10 min-w-0 items-center gap-1.5 overflow-x-auto rounded-md border border-border bg-white/[0.035] p-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] md:col-span-2 xl:col-span-1 2xl:h-12 2xl:gap-2">
            {[
              { value: "all" as const, label: "All" },
              ...trackedApplicationStatuses.map((item) => ({ value: item.status, label: item.label })),
            ].map((item) => {
              const isActive = selectedStatusFilter === item.value;

              return (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setSelectedStatusFilter(item.value)}
                  className={cn(
                    "h-7 shrink-0 rounded-md border px-2 text-[11px] font-bold transition 2xl:h-8 2xl:px-4 2xl:text-xs",
                    isActive
                      ? "border-accent/70 bg-accent/14 text-accent shadow-[0_0_0_1px_rgba(255,90,0,0.12)]"
                      : "border-border bg-white/[0.035] text-muted hover:bg-white/[0.07] hover:text-white",
                  )}
                >
                  {item.label}
                </button>
              );
            })}
          </div>

          <Button
            className="h-10 w-full justify-center rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-3 text-xs font-bold text-white shadow-[0_14px_30px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12] md:w-auto 2xl:h-12 2xl:px-6 2xl:text-sm"
            onClick={openManualApplicationDialog}
          >
            <Plus className="h-4 w-4 2xl:h-5 2xl:w-5" />
            Add application
          </Button>
        </div>
      </header>

      <div className="grid shrink-0 gap-2 sm:grid-cols-2 xl:grid-cols-5 2xl:gap-3">
        {statCards.map((stat) => (
          <article key={stat.label} className="panel flex min-h-[62px] items-center justify-between gap-2 p-2 2xl:min-h-[104px] 2xl:gap-3 2xl:p-4">
            <div className="min-w-0">
              <p className="text-[10px] font-semibold leading-tight text-muted 2xl:text-xs">{stat.label}</p>
              <p className="mt-0.5 text-[18px] font-bold leading-none text-white 2xl:mt-1.5 2xl:text-[26px]">{stat.value}</p>
            </div>
            <div className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-md border border-white/[0.08] 2xl:h-10 2xl:w-10", stat.iconClassName)}>
              <stat.icon className="h-3.5 w-3.5 2xl:h-4 2xl:w-4" />
            </div>
          </article>
        ))}
      </div>

      {applications.length === 0 ? (
        <section className="panel mt-3 grid min-h-0 flex-1 place-items-center p-6 text-center 2xl:mt-4">
          <div className="max-w-[440px]">
            <div className="mx-auto grid h-14 w-14 place-items-center rounded-md bg-accent/18 text-accent">
              <Mail className="h-7 w-7" />
            </div>
            <h2 className="mt-4 text-xl font-bold text-white">No applications yet</h2>
            <p className="mt-2 text-sm leading-6 text-muted">Add a vacancy manually or open Jobs and mark a found vacancy as applied.</p>
            <div className="mt-5 flex flex-col justify-center gap-2 sm:flex-row">
              <Button className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#dd3d00] px-5 text-[13px]" onClick={openManualApplicationDialog}>
                <Plus className="h-4 w-4" />
                Add application
              </Button>
              <Button variant="ghost" className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]" onClick={onOpenJobs}>
                Browse jobs
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </section>
      ) : (
        <div className="mt-2 grid min-h-0 flex-1 gap-3 xl:grid-cols-[minmax(280px,0.86fr)_minmax(360px,1.18fr)_minmax(240px,0.7fr)] 2xl:mt-3 2xl:grid-cols-[minmax(420px,0.95fr)_minmax(480px,1.2fr)_minmax(320px,0.75fr)] 2xl:gap-4">
          <aside className="panel flex min-h-0 flex-col overflow-hidden p-2.5 2xl:p-4">
            <div className="mb-2.5 flex items-center justify-between 2xl:mb-3">
              <h2 className="text-sm font-bold text-white 2xl:text-lg">Applications ({filteredApplications.length})</h2>
              <button type="button" className="inline-flex h-8 items-center gap-2 rounded-md border border-border bg-white/[0.035] px-3 text-xs font-bold text-[#d8dee8]">
                Date applied
                <ChevronDown className="h-3.5 w-3.5 text-muted" />
              </button>
            </div>
            <div className="job-scroll min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
              {filteredApplications.length === 0 ? (
                <div className="rounded-md border border-border bg-white/[0.025] p-4 text-sm leading-6 text-muted">
                  No applications match the current search or status filter.
                </div>
              ) : filteredApplications.map((application) => (
                <div
                  key={application.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelectApplication(application.id)}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" && event.key !== " ") return;
                    event.preventDefault();
                    onSelectApplication(application.id);
                  }}
                  className={cn(
                    "grid w-full cursor-pointer grid-cols-[44px_minmax(0,1fr)_auto_auto] items-center gap-2.5 rounded-md border p-2.5 text-left transition 2xl:grid-cols-[54px_minmax(0,1fr)_auto_auto_auto] 2xl:gap-3 2xl:p-4",
                    visibleSelectedApplication?.id === application.id
                      ? "border-accent bg-white/[0.055] shadow-[0_0_0_1px_rgba(255,90,0,0.12)]"
                      : "border-border bg-white/[0.025] hover:bg-white/[0.055]",
                  )}
                >
                  <JobRoleIcon job={application.job} />
                  <div className="min-w-0">
                    <h3 className="truncate text-[13px] font-bold text-white 2xl:text-base">{application.job.title}</h3>
                    <p className="mt-0.5 truncate text-[11px] font-semibold text-[#cdd4df] 2xl:text-sm">{application.job.company}</p>
                    <p className="mt-1 text-[11px] text-muted 2xl:hidden">{formatApplicationDate(application.appliedAt)} • {formatMatchValue(application.job)}</p>
                  </div>
                  <span className={cn("shrink-0 rounded-md border px-2 py-1 text-[10px] font-bold 2xl:text-[11px]", applicationStatusStyles[application.status])}>
                    {matchingApplicationIdSet.has(application.id) ? "Analyzing" : getApplicationStatusLabel(application.status)}
                  </span>
                  <button
                    type="button"
                    aria-label={`Open AI info for ${application.job.title}`}
                    title="AI info"
                    onClick={(event) => {
                      event.stopPropagation();
                      openApplicationAiInfo(application.id);
                    }}
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border text-muted transition hover:bg-white/[0.06] hover:text-white"
                  >
                    <Info className="h-4 w-4" />
                  </button>
                  <div className="hidden text-right 2xl:block">
                    <p className="text-xs font-semibold text-muted">{formatApplicationDate(application.appliedAt)}</p>
                    <p className="mt-1 text-sm font-bold text-success">{formatMatchValue(application.job)}</p>
                  </div>
                </div>
              ))}
            </div>
          </aside>

          <section className="panel min-h-0 overflow-hidden p-2.5 2xl:p-3">
            {visibleSelectedApplication ? (
              <div className="flex h-full min-h-0 flex-col">
                <div className="flex shrink-0 flex-col gap-2.5 lg:flex-row lg:items-start lg:justify-between">
                  <div className="flex min-w-0 items-start gap-2.5">
                    <JobRoleIcon job={visibleSelectedApplication.job} compact />
                    <div className="min-w-0">
                      <h2 className="text-[16px] font-bold leading-tight text-white 2xl:text-[18px]">{visibleSelectedApplication.job.title}</h2>
                      <p className="mt-0.5 text-[11px] font-semibold text-muted 2xl:text-xs">
                        {visibleSelectedApplication.job.company} <span className="text-white/35">•</span> {visibleSelectedApplication.job.location} <span className="text-white/35">•</span> {visibleSelectedApplication.job.type}
                      </p>
                      {visibleSelectedApplication.job.applyUrl || visibleSelectedApplication.job.sourceUrl ? (
                        <a
                          href={visibleSelectedApplication.job.applyUrl || visibleSelectedApplication.job.sourceUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1 inline-flex items-center gap-1.5 text-[10px] font-bold text-[#8cc7ff] hover:text-white 2xl:text-xs"
                        >
                          View job posting
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      ) : (
                        <p className="mt-2 text-sm font-semibold text-muted">{visibleSelectedApplication.job.salary}</p>
                      )}
                    </div>
                  </div>
                  <div className="relative flex shrink-0 items-center gap-2">
                    <Button
                      type="button"
                      onClick={() => onPrepareApplication(visibleSelectedApplication.id)}
                      className="h-8 rounded-md bg-accent px-3 text-[10px] font-bold text-white hover:bg-[#ff6a14] 2xl:h-9 2xl:text-xs"
                    >
                      <FileText className="h-3.5 w-3.5" />
                      Prepare
                    </Button>
                    <button
                      type="button"
                      aria-label="Open AI info"
                      title="AI info"
                      onClick={() => openApplicationAiInfo(visibleSelectedApplication.id)}
                      className="grid h-8 w-8 place-items-center rounded-md border border-border text-muted transition hover:bg-white/[0.06] hover:text-white 2xl:h-9 2xl:w-9"
                    >
                      <Info className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      aria-label="Application actions"
                      onClick={() => setIsApplicationMenuOpen((isOpen) => !isOpen)}
                      className="grid h-8 w-8 place-items-center rounded-md border border-border text-muted transition hover:bg-white/[0.06] hover:text-white 2xl:h-9 2xl:w-9"
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </button>

                    {isApplicationMenuOpen && (
                      <div className="absolute right-0 top-10 z-30 grid w-[184px] gap-1 rounded-md border border-border bg-[#101720] p-1.5 shadow-[0_18px_40px_rgba(0,0,0,0.42)]">
                        <button
                          type="button"
                          onClick={openApplicationPosting}
                          disabled={!visibleSelectedApplication.job.applyUrl && !visibleSelectedApplication.job.sourceUrl}
                          className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#e6ebf3] hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:text-muted/45 disabled:hover:bg-transparent"
                        >
                          Open job posting
                        </button>
                        <button
                          type="button"
                          onClick={() => openApplicationAiInfo(visibleSelectedApplication.id)}
                          className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#e6ebf3] hover:bg-white/[0.06]"
                        >
                          AI info
                        </button>
                        <div className="my-1 h-px bg-border" />
                        <p className="px-2 py-1 text-[10px] font-bold uppercase tracking-normal text-muted">Change status</p>
                        {trackedApplicationStatuses.map((item) => (
                          <button
                            key={item.status}
                            type="button"
                            onClick={() => changeApplicationStatus(item.status)}
                            className={cn(
                              "rounded-md px-2 py-1.5 text-left text-[11px] font-bold hover:bg-white/[0.06]",
                              visibleSelectedApplication.status === item.status ? "text-accent" : "text-[#e6ebf3]",
                            )}
                          >
                            {item.label}
                          </button>
                        ))}
                        <div className="my-1 h-px bg-border" />
                        <button
                          type="button"
                          onClick={deleteSelectedApplication}
                          className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#ff8a8a] hover:bg-[#d94d4d]/12"
                        >
                          Delete application
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                <section className="mt-2 shrink-0 rounded-md border border-border bg-white/[0.018] p-2 2xl:p-2.5">
                  <h3 className="text-[13px] font-bold text-white 2xl:text-sm">Status timeline</h3>
                  <div className="mt-2 space-y-0">
                    {timelineItems.map((item, index) => {
                      const event = item.event;

                      return (
                      <div key={`${item.label}-${index}`} className="grid grid-cols-[28px_minmax(0,1fr)] gap-2">
                        <div className="relative flex justify-center">
                          <span
                            className={cn(
                              "z-10 mt-0.5 grid h-4 w-4 place-items-center rounded-full border",
                              item.state === "done"
                                ? "border-accent bg-accent text-white"
                                : item.state === "rejected"
                                  ? "border-[#d94d4d] bg-[#d94d4d]/20 text-[#ff8a8a]"
                                  : item.state === "canceled"
                                    ? "border-white/25 bg-white/[0.04] text-muted"
                                : item.state === "current"
                                  ? "border-accent bg-accent/18"
                                  : "border-white/25 bg-white/[0.04]",
                            )}
                          >
                            {item.state === "done" && <Check className="h-2.5 w-2.5" />}
                            {(item.state === "canceled" || item.state === "rejected") && <X className="h-2.5 w-2.5" />}
                          </span>
                          {index < timelineItems.length - 1 && (
                            <span className={cn("absolute bottom-0 top-4 w-px", item.state === "done" ? "bg-accent" : "bg-white/18")} />
                          )}
                        </div>
                        <div className="relative pb-1.5">
                          <div className="flex items-center justify-between gap-3">
                            <p
                              className={cn(
                                "text-[12px] font-bold 2xl:text-[13px]",
                                item.state === "current" ? "text-accent" : item.state === "rejected" ? "text-[#ff8a8a]" : "text-white",
                              )}
                            >
                              {item.label}
                            </p>
                            <div className="flex shrink-0 items-center gap-1.5">
                              {item.state === "current" && (
                                <span className="rounded-md border border-accent/30 bg-accent/12 px-2 py-0.5 text-[10px] font-bold text-accent">Current</span>
                              )}
                              {event?.status === "completed" && (
                                <span className="rounded-md border border-success/30 bg-success/12 px-2 py-0.5 text-[10px] font-bold text-success">
                                  {getApplicationEventOutcomeLabel(event.outcome) || "Completed"}
                                </span>
                              )}
                              {event?.status === "canceled" && (
                                <span className="rounded-md border border-white/15 bg-white/[0.04] px-2 py-0.5 text-[10px] font-bold text-muted">Canceled</span>
                              )}
                              {event && (
                                <button
                                  type="button"
                                  aria-label="Event actions"
                                  onClick={() => setActiveEventMenuId((currentId) => (currentId === event.id ? "" : event.id))}
                                  className="grid h-6 w-6 place-items-center rounded-md border border-border text-muted transition hover:bg-white/[0.06] hover:text-white"
                                >
                                  <MoreHorizontal className="h-3.5 w-3.5" />
                                </button>
                              )}
                            </div>
                          </div>
                          <p className="mt-0.5 text-[10px] font-medium text-muted 2xl:text-[11px]">{item.date}</p>
                          {event && activeEventMenuId === event.id && (
                            <div className="absolute right-0 top-7 z-20 grid w-[158px] gap-1 rounded-md border border-border bg-[#101720] p-1.5 shadow-[0_16px_34px_rgba(0,0,0,0.38)]">
                              <button type="button" onClick={() => openEditEventDialog(event)} className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#e6ebf3] hover:bg-white/[0.06]">
                                Edit time
                              </button>
                              <button type="button" onClick={() => updateEvent(event, { status: "completed", outcome: "positive" })} className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#e6ebf3] hover:bg-white/[0.06]">
                                Mark completed
                              </button>
                              <button type="button" onClick={() => updateEvent(event, { status: "canceled", outcome: undefined })} className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#e6ebf3] hover:bg-white/[0.06]">
                                Mark canceled
                              </button>
                              <button type="button" onClick={() => updateEvent(event, { status: "completed", outcome: "negative" })} className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#ff8a8a] hover:bg-[#d94d4d]/12">
                                Mark rejected
                              </button>
                              <button type="button" onClick={() => deleteEvent(event.id)} className="rounded-md px-2 py-1.5 text-left text-[11px] font-bold text-[#ff8a8a] hover:bg-[#d94d4d]/12">
                                Delete
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                      );
                    })}
                  </div>
                </section>

                <section className="mt-2 shrink-0 rounded-md border border-border bg-white/[0.018] p-2 2xl:p-2.5">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <h3 className="flex items-center gap-2 text-[13px] font-bold text-white 2xl:text-sm">
                        <Calendar className="h-3.5 w-3.5 text-accent" />
                        Next action
                      </h3>
                      <p className="mt-1 text-[12px] font-semibold text-[#d8dee8] 2xl:text-[13px]">
                        {nextApplicationEvent ? nextApplicationEvent.title : "No event scheduled"}
                      </p>
                      <p className="mt-0.5 truncate text-[10px] text-muted 2xl:text-[11px]">
                        {nextApplicationEvent
                          ? `${formatApplicationEventDate(nextApplicationEvent.startsAt)} at ${formatApplicationEventTime(nextApplicationEvent.startsAt)}`
                          : "Schedule a screening, interview, assessment, or follow-up"}
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-7 rounded-md border border-border bg-transparent px-3 text-[11px] text-[#e6ebf3] hover:bg-white/[0.06]"
                      onClick={openScheduleDialog}
                    >
                      Schedule
                    </Button>
                  </div>
                </section>

                <section className="mt-2 shrink-0">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="text-[13px] font-bold text-white 2xl:text-sm">Documents used</h3>
                    <label className="inline-flex h-7 cursor-pointer items-center gap-2 rounded-md border border-border bg-transparent px-2.5 text-[11px] font-semibold text-[#e6ebf3] transition hover:bg-white/[0.06]">
                      <Upload className="h-3.5 w-3.5" />
                      Add document
                      <input
                        type="file"
                        accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg,image/webp"
                        className="hidden"
                        onChange={(event) => {
                          attachApplicationDocument(event.target.files?.[0]);
                          event.currentTarget.value = "";
                        }}
                      />
                    </label>
                  </div>
                  <div className="mt-1.5 overflow-hidden rounded-md border border-border">
                    {visibleSelectedApplication.documents.length === 0 ? (
                      <div className="bg-white/[0.018] px-2.5 py-3 text-[12px] font-semibold leading-5 text-muted 2xl:text-[13px]">
                        No documents attached yet.
                      </div>
                    ) : (
                      <div className="divide-y divide-border">
                        {visibleSelectedApplication.documents.map((document) => (
                          <div key={document.id} className="flex items-center gap-2.5 bg-white/[0.018] px-2.5 py-1.5 text-[12px] font-semibold text-[#d8dee8] 2xl:text-[13px]">
                            <span className="grid h-5 min-w-8 place-items-center rounded-sm bg-[#ff3d3d] px-1 text-[7px] font-black leading-none text-white">
                              {getApplicationDocumentBadge(document)}
                            </span>
                            <span className="min-w-0 flex-1 truncate" title={document.fileName}>
                              {document.title}
                              {document.fileSize ? <span className="font-medium text-muted"> • {document.fileSize}</span> : null}
                            </span>
                            <Info className="h-3.5 w-3.5 shrink-0 text-muted" />
                            <a
                              href={document.dataUrl}
                              download={document.fileName}
                              aria-label={`Download ${document.fileName}`}
                              title={`Download ${document.fileName}`}
                              className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted transition hover:bg-white/[0.06] hover:text-white"
                            >
                              <Download className="h-3.5 w-3.5" />
                            </a>
                            <button
                              type="button"
                              aria-label={`Delete ${document.fileName}`}
                              title={`Delete ${document.fileName}`}
                              onClick={() => deleteApplicationDocument(document.id)}
                              className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#d94d4d]/12 hover:text-[#ff8a8a]"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </section>

                <section className="mt-2 min-h-0 shrink rounded-md border border-border bg-white/[0.018] p-2 2xl:p-2.5">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="text-[13px] font-bold text-white 2xl:text-sm">Notes</h3>
                    <Button
                      variant="ghost"
                      className="h-7 rounded-md border border-border bg-transparent px-2.5 text-[11px] text-[#e6ebf3] hover:bg-white/[0.06]"
                      onClick={openNotesDialog}
                    >
                      Edit note
                    </Button>
                  </div>
                  <p className="mt-1.5 line-clamp-2 text-[11px] leading-4 text-muted 2xl:text-xs 2xl:leading-5">
                    {getVisibleApplicationNotes(visibleSelectedApplication.notes) || "No notes yet."}
                  </p>
                </section>
              </div>
            ) : (
              <div className="grid min-h-[320px] place-items-center text-center">
                <div className="max-w-[360px]">
                  <Search className="mx-auto h-8 w-8 text-muted" />
                  <h3 className="mt-3 text-base font-bold text-white">No matching application</h3>
                  <p className="mt-2 text-sm leading-6 text-muted">Adjust the search or choose another status filter.</p>
                </div>
              </div>
            )}
          </section>

          <aside className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-3 2xl:gap-4">
            <section className="panel p-3 2xl:p-5">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-bold text-white 2xl:text-lg">Upcoming</h2>
                <button type="button" onClick={onOpenCalendar} className="text-xs font-bold text-accent transition hover:text-[#ff8a45]">View calendar</button>
              </div>
              <div className="mt-4 space-y-3">
                {upcomingEvents.length > 0 ? upcomingEvents.map((event) => {
                  const application = applications.find((item) => item.id === event.applicationId);
                  if (!application) return null;
                  const eventDate = new Date(event.startsAt);

                  return (
                  <button
                    key={event.id}
                    type="button"
                    onClick={() => onSelectApplication(application.id)}
                    className="grid w-full grid-cols-[44px_minmax(0,1fr)_auto] items-center gap-2.5 rounded-md border border-border bg-white/[0.025] p-2.5 text-left transition hover:bg-white/[0.055] 2xl:grid-cols-[52px_minmax(0,1fr)_auto] 2xl:gap-3 2xl:p-3"
                  >
                    <div className="rounded-md border border-accent/45 bg-accent/10 py-1.5 text-center">
                      <p className="text-[9px] font-black uppercase text-accent 2xl:text-[10px]">
                        {Number.isNaN(eventDate.getTime()) ? "TBD" : eventDate.toLocaleDateString(undefined, { month: "short" })}
                      </p>
                      <p className="text-lg font-bold leading-none text-white 2xl:text-xl">
                        {Number.isNaN(eventDate.getTime()) ? "-" : eventDate.getDate()}
                      </p>
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-bold text-white">{event.title}</p>
                      <p className="mt-1 truncate text-xs text-muted">
                        {formatApplicationEventTime(event.startsAt)} • {application.job.company}
                      </p>
                    </div>
                    <span className="rounded-md bg-white/[0.06] px-2 py-1 text-[11px] font-bold text-muted">
                      {getApplicationEventTypeLabel(event.type)}
                    </span>
                  </button>
                  );
                }) : (
                  <button
                    type="button"
                    onClick={openScheduleDialog}
                    className="w-full rounded-md border border-dashed border-border bg-white/[0.018] p-3 text-left text-xs font-semibold leading-5 text-muted transition hover:border-accent/55 hover:text-white"
                  >
                    No scheduled events yet. Add a screening, interview, assessment deadline, or follow-up.
                  </button>
                )}
              </div>
            </section>

            <section className="panel h-full min-h-0 p-3 2xl:p-5">
              <h2 className="text-sm font-bold text-white 2xl:text-lg">AI Actions</h2>
              <div className="mt-3 grid gap-2 2xl:mt-4">
                {[
                  { label: "Follow-up", prompt: assistantPrompts.followUpApplication },
                  { label: "Prepare interview", prompt: assistantPrompts.prepareInterview },
                  { label: "Summarize fit", prompt: "Summarize my fit for this role, including the strongest evidence, gaps, and next step." },
                ].map((action) => (
                  <Button
                    key={action.label}
                    variant="ghost"
                    onClick={() => visibleSelectedApplication && onOpenAssistant(action.prompt, visibleSelectedApplication.id)}
                    disabled={!visibleSelectedApplication}
                    className="h-9 justify-start rounded-md border border-border bg-transparent text-xs text-[#e6ebf3] hover:bg-white/[0.06] disabled:opacity-45 2xl:h-11 2xl:text-[13px]"
                  >
                    <span className="grid h-6 w-6 place-items-center rounded-md bg-accent/14 text-accent 2xl:h-7 2xl:w-7">
                      <Sparkles className="h-3.5 w-3.5 2xl:h-4 2xl:w-4" />
                    </span>
                    {action.label}
                    <ChevronRight className="ml-auto h-4 w-4 text-muted" />
                  </Button>
                ))}
              </div>
            </section>

          </aside>
        </div>
      )}

      {aiInfoApplication && (
        <ApplicationAiInfoDialog
          application={aiInfoApplication}
          isAnalyzing={matchingApplicationIdSet.has(aiInfoApplication.id)}
          onClose={() => setAiInfoApplicationId("")}
        />
      )}

      {isManualApplicationDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
          <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[780px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5">
            <div className="flex shrink-0 items-start justify-between gap-4">
              <div>
                <h2 className="text-[22px] font-bold leading-tight text-white">Add application</h2>
                <p className="mt-1 text-sm font-medium text-muted">Create a tracked vacancy manually</p>
              </div>
              <button
                type="button"
                aria-label="Close manual application"
                onClick={() => setIsManualApplicationDialogOpen(false)}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="job-scroll mt-5 grid min-h-0 flex-1 gap-4 overflow-y-auto pr-1 md:grid-cols-2">
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Role title</span>
                <input
                  value={manualApplicationDraft.title}
                  onChange={(event) => updateManualApplicationDraft("title", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  placeholder="Senior Product Designer"
                />
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Company</span>
                <input
                  value={manualApplicationDraft.company}
                  onChange={(event) => updateManualApplicationDraft("company", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  placeholder="Company name"
                />
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Location</span>
                <input
                  value={manualApplicationDraft.location}
                  onChange={(event) => updateManualApplicationDraft("location", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  placeholder="Zurich, Remote, Europe"
                />
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Status</span>
                <select
                  value={manualApplicationDraft.status}
                  onChange={(event) => updateManualApplicationDraft("status", event.target.value as ApplicationStatus)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                >
                  {trackedApplicationStatuses.map((item) => (
                    <option key={item.status} value={item.status}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="grid gap-2 md:col-span-2">
                <span className="text-xs font-bold text-[#d8dee8]">Job posting URL</span>
                <input
                  value={manualApplicationDraft.applyUrl}
                  onChange={(event) => updateManualApplicationDraft("applyUrl", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  placeholder="https://company.com/careers/role"
                />
              </label>

              <section className="grid gap-2 rounded-md border border-border bg-white/[0.018] p-3 md:col-span-2">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h3 className="text-xs font-bold text-[#d8dee8]">Resume for this application</h3>
                    <p className="mt-1 text-xs font-medium text-muted">Choose the profile resume or upload a different one.</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-8 rounded-md border border-border bg-transparent px-3 text-[12px] text-[#e6ebf3] hover:bg-white/[0.06]"
                      disabled={!profile.resume_file_name || !profile.resume_data_url}
                      onClick={useProfileResumeForManualApplication}
                    >
                      <FileText className="h-3.5 w-3.5" />
                      Use profile resume
                    </Button>
                    <label className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-md border border-border bg-transparent px-3 text-[12px] font-semibold text-[#e6ebf3] transition hover:bg-white/[0.06]">
                      <Upload className="h-3.5 w-3.5" />
                      Upload another
                      <input
                        type="file"
                        accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        className="hidden"
                        onChange={(event) => {
                          attachManualApplicationResume(event.target.files?.[0]);
                          event.currentTarget.value = "";
                        }}
                      />
                    </label>
                  </div>
                </div>

                {manualApplicationDraft.documents.length > 0 ? (
                  <div className="mt-1 flex items-center gap-2.5 rounded-md border border-border bg-white/[0.025] px-2.5 py-2 text-[12px] font-semibold text-[#d8dee8]">
                    <span className="grid h-5 min-w-8 place-items-center rounded-sm bg-[#ff3d3d] px-1 text-[7px] font-black leading-none text-white">
                      {getApplicationDocumentBadge(manualApplicationDraft.documents[0])}
                    </span>
                    <span className="min-w-0 flex-1 truncate" title={manualApplicationDraft.documents[0].fileName}>
                      {manualApplicationDraft.documents[0].title}
                      {manualApplicationDraft.documents[0].fileSize ? (
                        <span className="font-medium text-muted"> • {manualApplicationDraft.documents[0].fileSize}</span>
                      ) : null}
                    </span>
                    <button
                      type="button"
                      aria-label="Remove selected resume"
                      title="Remove selected resume"
                      onClick={() => updateManualApplicationDraft("documents", [])}
                      className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#d94d4d]/12 hover:text-[#ff8a8a]"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ) : (
                  <p className="mt-1 rounded-md border border-dashed border-border bg-white/[0.018] px-2.5 py-2 text-[12px] font-semibold text-muted">
                    No resume selected for this application.
                  </p>
                )}
              </section>

              <label className="grid gap-2 md:col-span-2">
                <span className="text-xs font-bold text-[#d8dee8]">Vacancy description</span>
                <textarea
                  value={manualApplicationDraft.overview}
                  onChange={(event) => updateManualApplicationDraft("overview", event.target.value)}
                  className="min-h-[190px] resize-none rounded-md border border-border bg-[#0d131a] px-3 py-2 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  placeholder="Paste the vacancy description..."
                />
              </label>
            </div>

            <div className="mt-5 flex shrink-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs font-semibold text-muted">Title, company, location, link, and description are required.</p>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
                  onClick={() => setIsManualApplicationDialogOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-5 text-[13px] text-white"
                  disabled={
                    !manualApplicationDraft.title.trim() ||
                    !manualApplicationDraft.company.trim() ||
                    !manualApplicationDraft.location.trim() ||
                    !manualApplicationDraft.applyUrl.trim() ||
                    !manualApplicationDraft.overview.trim()
                  }
                  onClick={saveManualApplication}
                >
                  <Save className="h-4 w-4" />
                  Save application
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {isNotesDialogOpen && visibleSelectedApplication && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
          <div className="panel w-full max-w-[540px] border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-[22px] font-bold leading-tight text-white">Edit notes</h2>
                <p className="mt-1 text-sm font-medium text-muted">
                  {visibleSelectedApplication.job.company} • {visibleSelectedApplication.job.title}
                </p>
              </div>
              <button
                type="button"
                aria-label="Close notes editor"
                onClick={() => setIsNotesDialogOpen(false)}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <textarea
              value={applicationNotesDraft}
              onChange={(event) => setApplicationNotesDraft(event.target.value)}
              className="mt-5 min-h-[150px] w-full resize-none rounded-md border border-border bg-[#0d131a] px-3 py-2 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              placeholder="Add notes about this application..."
            />

            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <Button
                type="button"
                variant="ghost"
                className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
                onClick={() => setApplicationNotesDraft("")}
              >
                Clear
              </Button>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
                  onClick={() => setIsNotesDialogOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-5 text-[13px] text-white"
                  onClick={saveApplicationNotes}
                >
                  <Save className="h-4 w-4" />
                  Save notes
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {isScheduleDialogOpen && eventDraft && visibleSelectedApplication && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
          <div className="panel w-full max-w-[620px] border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-[22px] font-bold leading-tight text-white">{isEditingEvent ? "Edit event" : "Schedule event"}</h2>
                <p className="mt-1 text-sm font-medium text-muted">
                  {visibleSelectedApplication.job.company} • {visibleSelectedApplication.job.title}
                </p>
              </div>
              <button
                type="button"
                aria-label="Close schedule event"
                onClick={() => {
                  setIsScheduleDialogOpen(false);
                  setEventDraft(null);
                }}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mt-5 grid max-h-[72vh] gap-4 overflow-y-auto pr-1 md:grid-cols-2">
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Event type</span>
                <select
                  value={eventDraft.type}
                  onChange={(event) => updateEventDraft("type", event.target.value as ApplicationEventType)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                >
                  {applicationEventTypes.map((item) => (
                    <option key={item.type} value={item.type}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Status</span>
                <select
                  value={eventDraft.status}
                  onChange={(event) => updateEventDraft("status", event.target.value as ApplicationEventStatus)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                >
                  {applicationEventStatuses.map((item) => (
                    <option key={item.status} value={item.status}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Title</span>
                <input
                  value={eventDraft.title}
                  onChange={(event) => updateEventDraft("title", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  placeholder="Phone screen with recruiter"
                />
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Outcome</span>
                <select
                  value={eventDraft.outcome}
                  onChange={(event) => updateEventDraft("outcome", event.target.value as ApplicationEventOutcome | "")}
                  disabled={eventDraft.status !== "completed"}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70 disabled:cursor-not-allowed disabled:opacity-45"
                >
                  <option value="">No outcome yet</option>
                  {applicationEventOutcomes.map((item) => (
                    <option key={item.outcome} value={item.outcome}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Date and time</span>
                <input
                  type="datetime-local"
                  value={eventDraft.startsAt}
                  onChange={(event) => updateEventDraft("startsAt", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                />
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Duration</span>
                <select
                  value={eventDraft.durationMinutes}
                  onChange={(event) => updateEventDraft("durationMinutes", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                >
                  <option value="15">15 minutes</option>
                  <option value="30">30 minutes</option>
                  <option value="45">45 minutes</option>
                  <option value="60">1 hour</option>
                  <option value="90">1.5 hours</option>
                </select>
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Timezone</span>
                <input
                  value={eventDraft.timezone}
                  onChange={(event) => updateEventDraft("timezone", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  placeholder="Europe/Zurich"
                />
              </label>

              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Location or link</span>
                <input
                  value={eventDraft.location}
                  onChange={(event) => updateEventDraft("location", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  placeholder="Zoom, Google Meet, phone, office"
                />
              </label>

              <label className="grid gap-2 md:col-span-2">
                <span className="text-xs font-bold text-[#d8dee8]">Notes</span>
                <textarea
                  value={eventDraft.notes}
                  onChange={(event) => updateEventDraft("notes", event.target.value)}
                  className="min-h-[88px] resize-none rounded-md border border-border bg-[#0d131a] px-3 py-2 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  placeholder="Recruiter name, prep notes, agenda, questions..."
                />
              </label>
            </div>

            <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs font-semibold text-muted">Synced to backend with local fallback.</p>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  className="h-10 rounded-md border border-border bg-transparent px-5 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
                  onClick={() => {
                    setIsScheduleDialogOpen(false);
                    setEventDraft(null);
                  }}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-5 text-[13px] text-white"
                  disabled={!eventDraft.title.trim() || !eventDraft.startsAt}
                  onClick={saveEventDraft}
                >
                  <Save className="h-4 w-4" />
                  {isEditingEvent ? "Update event" : "Save event"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function ApplicationAiInfoDialog({
  application,
  isAnalyzing,
  onClose,
}: {
  application: TrackedApplication;
  isAnalyzing: boolean;
  onClose: () => void;
}) {
  const job = application.job;
  const breakdownItems = getAiMatchBreakdownItems(job);
  const reasons = job.aiMatch?.reasons.length ? job.aiMatch.reasons : ["No AI match reasons have been calculated yet."];
  const gaps = job.aiMatch?.gaps.length ? job.aiMatch.gaps : ["No AI match gaps have been calculated yet."];
  const recommendations = buildRecommendationPlan(job).slice(0, 5);
  const sourceDisplay = isAnalyzing ? "Analyzing..." : getAiMatchSourceDisplay(job);
  const rawExplanation = buildAiMatchRawExplanation(job);
  const signalStats = [
    { label: "Skills", value: job.skills.length.toString() },
    { label: "Requirements", value: job.requirements.length.toString() },
    { label: "Responsibilities", value: job.responsibilities.length.toString() },
    { label: "Documents", value: application.documents.length.toString() },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[920px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] 2xl:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <JobRoleIcon job={job} compact />
            <div className="min-w-0">
              <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">AI application info</h2>
              <p className="mt-1 truncate text-sm font-medium text-muted">
                {job.title} at {job.company}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close AI info"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto pr-1">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 2xl:gap-3">
            <InfoStat label="AI match" value={isAnalyzing ? "Analyzing..." : formatMatchValue(job)} />
            <InfoStat label="Source" value={sourceDisplay} title={job.aiMatch?.providerError} />
            <InfoStat label="Confidence" value={formatConfidence(job.aiMatch?.confidence)} />
            <InfoStat label="Updated" value={formatAiMatchTimestamp(job.aiMatch?.updatedAt)} />
          </div>

          {isAnalyzing ? (
            <div className="mt-4 rounded-md border border-accent/35 bg-accent/10 px-3 py-2 text-[13px] font-semibold text-[#ffd1b0] 2xl:text-sm">
              AI analysis is running. This panel will update automatically when the match result is saved.
            </div>
          ) : null}

          <section className="mt-4 rounded-md border border-border bg-white/[0.018] p-3 2xl:p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-bold text-white 2xl:text-base">Score breakdown</h3>
              <span className="rounded-md border border-success/30 bg-success/12 px-2 py-1 text-xs font-bold text-success">
                {isAnalyzing ? "Analyzing..." : formatMatchValue(job)}
              </span>
            </div>
            <div className="mt-3 space-y-2.5">
              {breakdownItems.map((item) => (
                <div key={item.key} className="grid grid-cols-[minmax(92px,0.34fr)_minmax(0,1fr)_54px] items-center gap-3">
                  <span className="text-[12px] font-semibold text-muted 2xl:text-sm">{item.label}</span>
                  <div className="h-2 rounded-full bg-white/[0.08]">
                    <div className="h-full rounded-full bg-success" style={{ width: `${item.progress}%` }} />
                  </div>
                  <span className="text-right text-[12px] font-bold text-[#d8dee8] 2xl:text-sm">
                    {item.value}/{item.max}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <section className="rounded-md border border-border bg-white/[0.018] p-3 2xl:p-4">
              <h3 className="text-sm font-bold text-white 2xl:text-base">Reasons</h3>
              <ul className="mt-2.5 space-y-2 text-[13px] leading-5 text-muted 2xl:text-sm">
                {reasons.map((item) => (
                  <li key={item} className="flex gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                    {item}
                  </li>
                ))}
              </ul>
            </section>

            <section className="rounded-md border border-border bg-white/[0.018] p-3 2xl:p-4">
              <h3 className="text-sm font-bold text-white 2xl:text-base">Gaps</h3>
              <ul className="mt-2.5 space-y-2 text-[13px] leading-5 text-muted 2xl:text-sm">
                {gaps.map((item) => (
                  <li key={item} className="flex gap-2">
                    <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-[#ffb020]" />
                    {item}
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section className="mt-4 rounded-md border border-border bg-white/[0.018] p-3 2xl:p-4">
            <h3 className="text-sm font-bold text-white 2xl:text-base">Extracted vacancy signals</h3>
            <div className="mt-3 grid gap-2 sm:grid-cols-4">
              {signalStats.map((item) => (
                <InfoStat key={item.label} label={item.label} value={item.value} />
              ))}
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <div>
                <h4 className="text-[12px] font-bold text-[#d8dee8] 2xl:text-sm">Skills</h4>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {job.skills.map((skill) => (
                    <span key={skill} className="rounded-md border border-border bg-white/[0.035] px-2 py-1 text-[11px] font-bold text-muted">
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <h4 className="text-[12px] font-bold text-[#d8dee8] 2xl:text-sm">Requirements</h4>
                <ul className="mt-2 space-y-1.5 text-[12px] leading-5 text-muted 2xl:text-[13px]">
                  {job.requirements.slice(0, 5).map((item) => (
                    <li key={item} className="flex gap-2">
                      <CircleDot className="mt-1 h-3 w-3 shrink-0 text-accent" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h4 className="text-[12px] font-bold text-[#d8dee8] 2xl:text-sm">Responsibilities</h4>
                <ul className="mt-2 space-y-1.5 text-[12px] leading-5 text-muted 2xl:text-[13px]">
                  {job.responsibilities.slice(0, 5).map((item) => (
                    <li key={item} className="flex gap-2">
                      <CircleDot className="mt-1 h-3 w-3 shrink-0 text-accent" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </section>

          <section className="mt-4 rounded-md border border-border bg-white/[0.018] p-3 2xl:p-4">
            <h3 className="text-sm font-bold text-white 2xl:text-base">Evidence-backed recommendations</h3>
            <div className="mt-2 divide-y divide-border">
              {recommendations.length ? recommendations.map((recommendation) => (
                <div key={`${recommendation.text}-${recommendation.gain}`} className="grid gap-1.5 py-2.5 text-[13px] leading-5 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)_auto] sm:items-start 2xl:text-sm">
                  <div>
                    <p className="font-bold text-[#d8dee8]">{recommendation.text}</p>
                    <p className="mt-0.5 text-muted">{recommendation.action}</p>
                  </div>
                  <p className="text-muted">{recommendation.why}</p>
                  <p className="font-bold text-success sm:text-right">{recommendation.gain}</p>
                </div>
              )) : <p className="py-2.5 text-[13px] leading-5 text-muted 2xl:text-sm">No source-backed recommendations are available.</p>}
            </div>
          </section>

          <section className="mt-4 rounded-md border border-border bg-white/[0.018] p-3 2xl:p-4">
            <h3 className="text-sm font-bold text-white 2xl:text-base">Explanation</h3>
            <p className="mt-2 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">{rawExplanation}</p>
          </section>
        </div>
      </div>
    </div>
  );
}

function SettingsView({
  settings,
  showLogs,
  apiKeyDraft,
  status,
  message,
  aiStatus,
  aiMessage,
  onApiKeyChange,
  onClear,
  onSave,
  onSaveAi,
  onShowLogsChange,
}: {
  settings: AppSettings;
  showLogs: boolean;
  apiKeyDraft: string;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  aiStatus: "idle" | "loading" | "ready" | "error";
  aiMessage: string;
  onApiKeyChange: (value: string) => void;
  onClear: () => void;
  onSave: () => void;
  onSaveAi: (update: AppSettingsUpdate) => void;
  onShowLogsChange: (value: boolean) => void;
}) {
  const hasApiKeyDraft = apiKeyDraft.trim().length > 0;
  const [aiBackendDraft, setAiBackendDraft] = useState<AIBackendName>(settings.ai_backend);
  const [openAiApiKeyDraft, setOpenAiApiKeyDraft] = useState("");
  const [openAiModelDraft, setOpenAiModelDraft] = useState(settings.openai_api_model);
  const [openAiReasoningDraft, setOpenAiReasoningDraft] = useState<OpenAIReasoningEffort>(
    settings.openai_api_reasoning_effort,
  );
  const [openAiTimeoutDraft, setOpenAiTimeoutDraft] = useState(settings.openai_api_timeout_seconds);
  const [openAiAttemptsDraft, setOpenAiAttemptsDraft] = useState(settings.openai_api_max_attempts);
  const [openAiBackoffDraft, setOpenAiBackoffDraft] = useState(settings.openai_api_retry_backoff_seconds);
  const [aiMatchModelDraft, setAiMatchModelDraft] = useState(settings.ai_match_model);
  const [aiMatchReasoningDraft, setAiMatchReasoningDraft] = useState<AIWorkloadReasoningEffort>(
    settings.ai_match_reasoning,
  );
  const [aiMatchBatchSizeDraft, setAiMatchBatchSizeDraft] = useState(settings.ai_match_batch_size);
  const [aiMatchTimeoutDraft, setAiMatchTimeoutDraft] = useState(settings.ai_match_timeout_seconds);
  const [aiMatchAttemptsDraft, setAiMatchAttemptsDraft] = useState(settings.ai_match_max_attempts);
  const [screeningModelDraft, setScreeningModelDraft] = useState(settings.job_screening_model);
  const [screeningReasoningDraft, setScreeningReasoningDraft] = useState<AIWorkloadReasoningEffort>(
    settings.job_screening_reasoning,
  );
  const [screeningBatchSizeDraft, setScreeningBatchSizeDraft] = useState(settings.job_screening_batch_size);
  const [screeningTimeoutDraft, setScreeningTimeoutDraft] = useState(settings.job_screening_timeout_seconds);
  const [screeningAttemptsDraft, setScreeningAttemptsDraft] = useState(settings.job_screening_max_attempts);
  const [screeningDescriptionLimitDraft, setScreeningDescriptionLimitDraft] = useState(
    settings.job_screening_max_description_chars,
  );
  const [isCurrentKeyVisible, setIsCurrentKeyVisible] = useState(false);
  const [revealedCurrentKey, setRevealedCurrentKey] = useState("");
  const [isCurrentKeyLoading, setIsCurrentKeyLoading] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const hasUsableOpenAiKey = settings.openai_api_key_configured || Boolean(openAiApiKeyDraft.trim());
  const aiConnectionValidationMessage = aiBackendDraft === "openai_api"
    ? !hasUsableOpenAiKey
      ? "Add an OpenAI API key before enabling this mode."
      : !openAiModelDraft.trim()
        ? "Enter a default OpenAI model before enabling this mode."
        : !Number.isFinite(openAiTimeoutDraft) || openAiTimeoutDraft < 10 || openAiTimeoutDraft > 600
          ? "OpenAI timeout must be between 10 and 600 seconds."
          : !Number.isInteger(openAiAttemptsDraft) || openAiAttemptsDraft < 1 || openAiAttemptsDraft > 4
            ? "OpenAI max attempts must be between 1 and 4."
            : !Number.isFinite(openAiBackoffDraft) || openAiBackoffDraft < 0 || openAiBackoffDraft > 10
              ? "OpenAI retry backoff must be between 0 and 10 seconds."
              : ""
    : "";
  const aiMatchValidationMessage = !aiMatchModelDraft.trim()
    ? "Enter a model for Full AI Match."
    : !Number.isInteger(aiMatchBatchSizeDraft) || aiMatchBatchSizeDraft < 1 || aiMatchBatchSizeDraft > 100
      ? "Full AI Match batch size must be between 1 and 100."
      : !Number.isFinite(aiMatchTimeoutDraft) || aiMatchTimeoutDraft < 10 || aiMatchTimeoutDraft > 600
        ? "Full AI Match timeout must be between 10 and 600 seconds."
        : !Number.isInteger(aiMatchAttemptsDraft) || aiMatchAttemptsDraft < 1 || aiMatchAttemptsDraft > 4
          ? "Full AI Match max attempts must be between 1 and 4."
          : "";
  const screeningValidationMessage = !screeningModelDraft.trim()
    ? "Enter a model for vacancy pre-screening."
    : !Number.isInteger(screeningBatchSizeDraft) || screeningBatchSizeDraft < 1 || screeningBatchSizeDraft > 100
      ? "Pre-screening batch size must be between 1 and 100."
      : !Number.isFinite(screeningTimeoutDraft) || screeningTimeoutDraft < 10 || screeningTimeoutDraft > 600
        ? "Pre-screening timeout must be between 10 and 600 seconds."
        : !Number.isInteger(screeningAttemptsDraft) || screeningAttemptsDraft < 1 || screeningAttemptsDraft > 4
          ? "Pre-screening max attempts must be between 1 and 4."
          : !Number.isInteger(screeningDescriptionLimitDraft)
              || screeningDescriptionLimitDraft < 1_000
              || screeningDescriptionLimitDraft > 200_000
            ? "Pre-screening description limit must be between 1,000 and 200,000 characters."
            : "";
  const aiValidationMessage =
    aiConnectionValidationMessage || aiMatchValidationMessage || screeningValidationMessage;
  const currentKeyPreview = settings.brightdata_api_key_preview || "No key saved";
  const displayedCurrentKey =
    settings.has_brightdata_api_key && isCurrentKeyVisible
      ? revealedCurrentKey || (isCurrentKeyLoading ? "Loading key..." : currentKeyPreview)
      : settings.has_brightdata_api_key
        ? currentKeyPreview
        : "No key saved";
  const statusMessage =
    status === "error"
      ? message || "Settings save failed"
      : copyStatus ||
        message ||
        (settings.has_brightdata_api_key
          ? "Key is encrypted and stored securely"
          : "Add a Bright Data key to enable LinkedIn and Indeed vacancy search.");

  useEffect(() => {
    setIsCurrentKeyVisible(false);
    setRevealedCurrentKey("");
    setCopyStatus("");
  }, [settings.brightdata_api_key_preview, settings.has_brightdata_api_key]);

  useEffect(() => {
    setAiBackendDraft(settings.ai_backend);
    setOpenAiApiKeyDraft("");
    setOpenAiModelDraft(settings.openai_api_model);
    setOpenAiReasoningDraft(settings.openai_api_reasoning_effort);
    setOpenAiTimeoutDraft(settings.openai_api_timeout_seconds);
    setOpenAiAttemptsDraft(settings.openai_api_max_attempts);
    setOpenAiBackoffDraft(settings.openai_api_retry_backoff_seconds);
    setAiMatchModelDraft(settings.ai_match_model);
    setAiMatchReasoningDraft(settings.ai_match_reasoning);
    setAiMatchBatchSizeDraft(settings.ai_match_batch_size);
    setAiMatchTimeoutDraft(settings.ai_match_timeout_seconds);
    setAiMatchAttemptsDraft(settings.ai_match_max_attempts);
    setScreeningModelDraft(settings.job_screening_model);
    setScreeningReasoningDraft(settings.job_screening_reasoning);
    setScreeningBatchSizeDraft(settings.job_screening_batch_size);
    setScreeningTimeoutDraft(settings.job_screening_timeout_seconds);
    setScreeningAttemptsDraft(settings.job_screening_max_attempts);
    setScreeningDescriptionLimitDraft(settings.job_screening_max_description_chars);
  }, [
    settings.ai_match_batch_size,
    settings.ai_match_max_attempts,
    settings.ai_match_model,
    settings.ai_match_reasoning,
    settings.ai_match_timeout_seconds,
    settings.ai_backend,
    settings.job_screening_batch_size,
    settings.job_screening_max_attempts,
    settings.job_screening_max_description_chars,
    settings.job_screening_model,
    settings.job_screening_reasoning,
    settings.job_screening_timeout_seconds,
    settings.openai_api_key_configured,
    settings.openai_api_key_preview,
    settings.openai_api_max_attempts,
    settings.openai_api_model,
    settings.openai_api_reasoning_effort,
    settings.openai_api_retry_backoff_seconds,
    settings.openai_api_timeout_seconds,
  ]);

  function saveAiBackendSettings() {
    onSaveAi({
      ai_backend: aiBackendDraft,
      ...(openAiApiKeyDraft.trim() ? { openai_api_key: openAiApiKeyDraft.trim() } : {}),
      openai_api_model: openAiModelDraft.trim(),
      openai_api_reasoning_effort: openAiReasoningDraft,
      openai_api_timeout_seconds: openAiTimeoutDraft,
      openai_api_max_attempts: openAiAttemptsDraft,
      openai_api_retry_backoff_seconds: openAiBackoffDraft,
      ai_match_model: aiMatchModelDraft.trim(),
      ai_match_reasoning: aiMatchReasoningDraft,
      ai_match_batch_size: aiMatchBatchSizeDraft,
      ai_match_timeout_seconds: aiMatchTimeoutDraft,
      ai_match_max_attempts: aiMatchAttemptsDraft,
      job_screening_model: screeningModelDraft.trim(),
      job_screening_reasoning: screeningReasoningDraft,
      job_screening_batch_size: screeningBatchSizeDraft,
      job_screening_timeout_seconds: screeningTimeoutDraft,
      job_screening_max_attempts: screeningAttemptsDraft,
      job_screening_max_description_chars: screeningDescriptionLimitDraft,
    });
  }

  function clearOpenAiApiKey() {
    setAiBackendDraft("openclaw_codex");
    setOpenAiApiKeyDraft("");
    onSaveAi({ ai_backend: "openclaw_codex", openai_api_key: "" });
  }

  async function loadCurrentApiKey() {
    if (!settings.has_brightdata_api_key) return "";
    if (revealedCurrentKey) return revealedCurrentKey;

    try {
      setIsCurrentKeyLoading(true);
      const response = await fetch(`${apiBaseUrl}/settings/brightdata-key`, { cache: "no-store" });
      const data = (await response.json()) as BrightDataApiKeyResponse;

      if (!response.ok) {
        throw new Error(data.detail ?? "Current key request failed");
      }

      const fullKey = data.brightdata_api_key ?? "";
      setRevealedCurrentKey(fullKey);
      return fullKey;
    } catch {
      setCopyStatus("Could not load current key");
      window.setTimeout(() => setCopyStatus(""), 2000);
      return "";
    } finally {
      setIsCurrentKeyLoading(false);
    }
  }

  async function toggleCurrentKeyVisibility() {
    if (isCurrentKeyVisible) {
      setIsCurrentKeyVisible(false);
      return;
    }

    const fullKey = await loadCurrentApiKey();
    if (fullKey) {
      setIsCurrentKeyVisible(true);
    }
  }

  async function copyCurrentKey() {
    const fullKey = await loadCurrentApiKey();
    if (!fullKey) return;

    try {
      await navigator.clipboard.writeText(fullKey);
      setCopyStatus("Current key copied");
      window.setTimeout(() => setCopyStatus(""), 2000);
    } catch {
      setCopyStatus("Copy failed");
      window.setTimeout(() => setCopyStatus(""), 2000);
    }
  }

  return (
    <section className="job-scroll flex h-screen min-w-0 flex-1 flex-col overflow-y-auto px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-4 flex shrink-0 flex-col gap-3 md:flex-row md:items-start md:justify-between 2xl:mb-5">
        <div>
          <h1 className="text-[24px] font-bold leading-tight tracking-normal text-white sm:text-[27px] 2xl:text-[31px]">
            Settings
          </h1>
          <p className="mt-1 text-[13px] text-muted 2xl:mt-1.5 2xl:text-base">Application credentials and integrations</p>
        </div>
      </header>

      <div className="grid max-w-[1460px] gap-5">
        <section className="panel p-4 2xl:p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-md bg-accent/18 text-accent 2xl:h-12 2xl:w-12">
                <FileText className="h-5 w-5 2xl:h-6 2xl:w-6" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-bold text-white 2xl:text-lg">Logs</h2>
                <p className="mt-1 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
                  Show the Logs button in the sidebar and keep local application events.
                </p>
              </div>
            </div>
            <button
              type="button"
              aria-label="Show logs"
              aria-pressed={showLogs}
              onClick={() => onShowLogsChange(!showLogs)}
              className={cn(
                "relative h-6 w-11 shrink-0 rounded-full transition",
                showLogs ? "bg-accent shadow-[0_0_14px_rgba(255,90,0,0.22)]" : "bg-white/15",
              )}
            >
              <span className={cn("absolute top-1 h-4 w-4 rounded-full bg-white transition", showLogs ? "right-1" : "left-1")} />
            </button>
          </div>
        </section>

        <section className="panel p-5 2xl:p-7">
          <div className="flex flex-col gap-4 md:flex-row md:items-start">
            <div className="flex min-w-0 items-start gap-3">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-md bg-accent/18 text-accent 2xl:h-12 2xl:w-12">
                <BrainCircuit className="h-5 w-5 2xl:h-6 2xl:w-6" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-bold text-white 2xl:text-lg">AI backend</h2>
                <p className="mt-1 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
                  Choose how Rufina sends new AI operations. Running operations keep the mode they started with.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-6 grid gap-5">
            <fieldset>
              <legend className="sr-only">AI mode</legend>
              <div className="grid gap-3 lg:grid-cols-2">
                {([
                  {
                    value: "openclaw_codex" as const,
                    title: "Codex credits via OpenClaw",
                    description: "Use the configured OpenClaw/Codex route and its available Codex credits.",
                  },
                  {
                    value: "openai_api" as const,
                    title: "OpenAI API",
                    description: "Call the OpenAI Responses API directly with your server-side API key.",
                  },
                ]).map((option) => {
                  const selected = aiBackendDraft === option.value;
                  return (
                    <label
                      key={option.value}
                      className={cn(
                        "cursor-pointer rounded-xl border p-4 transition",
                        selected
                          ? "border-accent/70 bg-accent/[0.09] shadow-[0_0_0_1px_rgba(255,90,0,0.16)]"
                          : "border-border bg-white/[0.025] hover:border-white/20 hover:bg-white/[0.045]",
                      )}
                    >
                      <span className="flex items-start gap-3">
                        <input
                          type="radio"
                          name="ai-backend"
                          value={option.value}
                          checked={selected}
                          onChange={() => setAiBackendDraft(option.value)}
                          className="mt-1 h-4 w-4 accent-[#ff5a00]"
                        />
                        <span>
                          <span className="block text-sm font-bold text-white 2xl:text-base">{option.title}</span>
                          <span className="mt-1 block text-xs leading-5 text-muted">{option.description}</span>
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <div className="rounded-lg border border-sky-400/20 bg-sky-400/[0.07] px-4 py-3 text-xs leading-5 text-sky-100">
              Switching applies to new operations. Running chat, document generation, imports, snapshots, and matching jobs keep the mode they started with.
            </div>

            {aiBackendDraft === "openai_api" ? (
              <div className="grid gap-5 rounded-xl border border-white/[0.08] bg-black/15 p-4 sm:p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-bold text-white">OpenAI API configuration</h3>
                    <p className="mt-1 text-xs text-muted">The full key remains server-side and is never returned to the browser.</p>
                  </div>
                  <span className={cn(
                    "rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.08em]",
                    hasUsableOpenAiKey
                      ? "border-success/30 bg-success/10 text-success"
                      : "border-red-400/30 bg-red-500/10 text-red-300",
                  )}>
                    {openAiApiKeyDraft.trim() ? "New key ready" : settings.openai_api_key_configured ? "Key configured" : "Key required"}
                  </span>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8] 2xl:text-base">OpenAI API key</span>
                    <input
                      type="password"
                      aria-label="OpenAI API key"
                      value={openAiApiKeyDraft}
                      onChange={(event) => setOpenAiApiKeyDraft(event.target.value)}
                      placeholder={settings.openai_api_key_preview || "Enter an OpenAI API key"}
                      className="h-12 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70 2xl:h-[52px] 2xl:px-4 2xl:text-base"
                      autoComplete="off"
                    />
                    <span className="text-xs font-medium text-muted">
                      {settings.openai_api_key_configured
                        ? `Saved key: ${settings.openai_api_key_preview}. Leave blank to keep it.`
                        : "No API key is configured."}
                    </span>
                  </label>

                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8] 2xl:text-base">OpenAI model</span>
                    <input
                      aria-label="OpenAI model"
                      value={openAiModelDraft}
                      onChange={(event) => setOpenAiModelDraft(event.target.value)}
                      className="h-12 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70 2xl:h-[52px] 2xl:px-4 2xl:text-base"
                    />
                  </label>
                </div>

                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Reasoning effort</span>
                    <select aria-label="OpenAI reasoning effort" value={openAiReasoningDraft} onChange={(event) => setOpenAiReasoningDraft(event.target.value as OpenAIReasoningEffort)} className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70">
                      {(["none", "low", "medium", "high", "xhigh", "max"] as OpenAIReasoningEffort[]).map((effort) => <option key={effort} value={effort}>{effort}</option>)}
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Timeout, seconds</span>
                    <input type="number" aria-label="OpenAI timeout seconds" min={10} max={600} value={openAiTimeoutDraft} onChange={(event) => setOpenAiTimeoutDraft(Number(event.target.value))} className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70" />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Max attempts</span>
                    <input type="number" aria-label="OpenAI max attempts" min={1} max={4} value={openAiAttemptsDraft} onChange={(event) => setOpenAiAttemptsDraft(Number(event.target.value))} className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70" />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Retry backoff, seconds</span>
                    <input type="number" aria-label="OpenAI retry backoff seconds" min={0} max={10} step={0.1} value={openAiBackoffDraft} onChange={(event) => setOpenAiBackoffDraft(Number(event.target.value))} className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70" />
                  </label>
                </div>
              </div>
            ) : settings.openai_api_key_configured ? (
              <div className="flex flex-col gap-3 rounded-lg border border-white/[0.08] bg-white/[0.025] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-white">OpenAI API key saved but not in use</p>
                  <p className="mt-1 text-xs text-muted">{settings.openai_api_key_preview} remains stored for a future switch to OpenAI API.</p>
                </div>
                <Button type="button" variant="ghost" className="h-10 shrink-0 rounded-md border border-red-400/25 px-4 text-xs text-red-200 hover:bg-red-500/10" disabled={aiStatus === "loading"} onClick={clearOpenAiApiKey}>
                  Delete saved OpenAI API key
                </Button>
              </div>
            ) : null}

            <div className="grid gap-4 xl:grid-cols-2">
              <section className="grid content-start gap-5 rounded-xl border border-amber-300/20 bg-amber-300/[0.045] p-4 sm:p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-bold text-white 2xl:text-base">Vacancy pre-screening</h3>
                      <span className="rounded-full border border-amber-300/25 bg-amber-300/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-amber-200">
                        Cheap model
                      </span>
                    </div>
                    <p className="mt-1.5 text-xs leading-5 text-muted">
                      Runs first and hides rejected vacancies from the client. Decisions follow only each search config.
                    </p>
                  </div>
                </div>

                <label className="grid gap-2">
                  <span className="text-sm font-bold text-[#d8dee8]">Model</span>
                  <input
                    aria-label="Vacancy pre-screening model"
                    value={screeningModelDraft}
                    onChange={(event) => setScreeningModelDraft(event.target.value)}
                    placeholder="openai/gpt-5-mini"
                    className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/60 focus:border-amber-300/60"
                  />
                </label>

                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Reasoning</span>
                    <select
                      aria-label="Vacancy pre-screening reasoning"
                      value={screeningReasoningDraft}
                      onChange={(event) => setScreeningReasoningDraft(event.target.value as AIWorkloadReasoningEffort)}
                      className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-amber-300/60"
                    >
                      {(["off", "low", "medium", "high", "xhigh", "max"] as AIWorkloadReasoningEffort[]).map((effort) => (
                        <option key={effort} value={effort}>{effort}</option>
                      ))}
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Jobs per request</span>
                    <input
                      type="number"
                      aria-label="Vacancy pre-screening batch size"
                      min={1}
                      max={100}
                      value={screeningBatchSizeDraft}
                      onChange={(event) => setScreeningBatchSizeDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-amber-300/60"
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Timeout, seconds</span>
                    <input
                      type="number"
                      aria-label="Vacancy pre-screening timeout seconds"
                      min={10}
                      max={600}
                      value={screeningTimeoutDraft}
                      onChange={(event) => setScreeningTimeoutDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-amber-300/60"
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Max attempts</span>
                    <input
                      type="number"
                      aria-label="Vacancy pre-screening max attempts"
                      min={1}
                      max={4}
                      value={screeningAttemptsDraft}
                      onChange={(event) => setScreeningAttemptsDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-amber-300/60"
                    />
                  </label>
                </div>

                <label className="grid gap-2">
                  <span className="text-sm font-bold text-[#d8dee8]">Description limit, characters</span>
                  <input
                    type="number"
                    aria-label="Vacancy pre-screening description limit"
                    min={1_000}
                    max={200_000}
                    step={1_000}
                    value={screeningDescriptionLimitDraft}
                    onChange={(event) => setScreeningDescriptionLimitDraft(Number(event.target.value))}
                    className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-amber-300/60"
                  />
                </label>
              </section>

              <section className="grid content-start gap-5 rounded-xl border border-accent/25 bg-accent/[0.045] p-4 sm:p-5">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-bold text-white 2xl:text-base">Full AI Match</h3>
                    <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-orange-200">
                      Main model
                    </span>
                  </div>
                  <p className="mt-1.5 text-xs leading-5 text-muted">
                    Runs only for vacancies that passed pre-screening and builds the detailed match analysis.
                  </p>
                </div>

                <label className="grid gap-2">
                  <span className="text-sm font-bold text-[#d8dee8]">Model</span>
                  <input
                    aria-label="Full AI Match model"
                    value={aiMatchModelDraft}
                    onChange={(event) => setAiMatchModelDraft(event.target.value)}
                    placeholder="openai/gpt-5.6-terra"
                    className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/60 focus:border-accent/70"
                  />
                </label>

                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Reasoning</span>
                    <select
                      aria-label="Full AI Match reasoning"
                      value={aiMatchReasoningDraft}
                      onChange={(event) => setAiMatchReasoningDraft(event.target.value as AIWorkloadReasoningEffort)}
                      className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                    >
                      {(["off", "low", "medium", "high", "xhigh", "max"] as AIWorkloadReasoningEffort[]).map((effort) => (
                        <option key={effort} value={effort}>{effort}</option>
                      ))}
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Jobs per request</span>
                    <input
                      type="number"
                      aria-label="Full AI Match batch size"
                      min={1}
                      max={100}
                      value={aiMatchBatchSizeDraft}
                      onChange={(event) => setAiMatchBatchSizeDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Timeout, seconds</span>
                    <input
                      type="number"
                      aria-label="Full AI Match timeout seconds"
                      min={10}
                      max={600}
                      value={aiMatchTimeoutDraft}
                      onChange={(event) => setAiMatchTimeoutDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-bold text-[#d8dee8]">Max attempts</span>
                    <input
                      type="number"
                      aria-label="Full AI Match max attempts"
                      min={1}
                      max={4}
                      value={aiMatchAttemptsDraft}
                      onChange={(event) => setAiMatchAttemptsDraft(Number(event.target.value))}
                      className="h-11 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                    />
                  </label>
                </div>
              </section>
            </div>

            {aiValidationMessage ? <p role="alert" className="text-sm font-semibold text-red-300">{aiValidationMessage}</p> : null}

            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <p className={cn("flex items-center gap-3 text-sm font-semibold", aiStatus === "error" ? "text-[#ff7a7a]" : aiStatus === "ready" ? "text-success" : "text-muted")}>
                {aiStatus === "error" ? <X className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />}
                {aiMessage || (settings.ai_backend === "openai_api" ? "OpenAI API is active" : "Codex credits via OpenClaw is active")}
              </p>
              <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                {aiBackendDraft === "openai_api" && settings.openai_api_key_configured && (
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-12 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
                    disabled={aiStatus === "loading"}
                    onClick={clearOpenAiApiKey}
                  >
                    Delete saved OpenAI API key
                  </Button>
                )}
                <Button
                  type="button"
                  className="h-12 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white"
                  disabled={
                    aiStatus === "loading"
                    || Boolean(aiValidationMessage)
                  }
                  onClick={saveAiBackendSettings}
                >
                  <Save className="h-4 w-4" />
                  {aiStatus === "loading" ? "Saving..." : "Save AI settings"}
                </Button>
              </div>
            </div>
          </div>
        </section>

        <section className="panel p-5 2xl:p-7">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-md bg-[#0a66c2]/22 text-[#8cc7ff] 2xl:h-12 2xl:w-12">
                <KeyRound className="h-5 w-5 2xl:h-6 2xl:w-6" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-bold text-white 2xl:text-lg">Bright Data</h2>
                <p className="mt-1 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
                  LinkedIn and Indeed vacancy search use this server-side API key.
                </p>
              </div>
            </div>
            <span
              className={cn(
                "inline-flex h-8 w-fit items-center gap-2 rounded-md border px-3 text-xs font-bold",
                settings.has_brightdata_api_key
                  ? "border-success/35 bg-success/12 text-success"
                  : "border-white/[0.12] bg-white/[0.055] text-muted",
              )}
            >
              {settings.has_brightdata_api_key ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
              {settings.has_brightdata_api_key ? "Configured" : "Not configured"}
            </span>
          </div>

          <div className="mt-6 grid gap-5">
            <div className="grid gap-2">
              <p className="text-sm font-bold text-[#d8dee8] 2xl:text-base">Current key</p>
              <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
                <div className="flex min-w-0 overflow-hidden rounded-md border border-border bg-[#0d131a]">
                  <div className="min-w-0 flex-1 px-3 py-3 font-mono text-sm font-semibold text-muted 2xl:px-4 2xl:text-base">
                    {displayedCurrentKey}
                  </div>
                  <button
                    type="button"
                    aria-label={isCurrentKeyVisible ? "Hide current key" : "Show current key"}
                    className="grid w-12 shrink-0 place-items-center border-l border-border text-muted transition hover:bg-white/[0.055] hover:text-white 2xl:w-14"
                    disabled={!settings.has_brightdata_api_key || isCurrentKeyLoading}
                    onClick={toggleCurrentKeyVisibility}
                  >
                    <Eye className="h-5 w-5" />
                  </button>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  className="h-12 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06] lg:w-[112px] 2xl:h-[52px] 2xl:text-sm"
                  disabled={!settings.has_brightdata_api_key || isCurrentKeyLoading}
                  onClick={copyCurrentKey}
                >
                  <Copy className="h-4 w-4" />
                  Copy
                </Button>
              </div>
            </div>

            <label className="grid gap-2">
              <span className="text-sm font-bold text-[#d8dee8] 2xl:text-base">Bright Data API key</span>
              <input
                type="password"
                value={apiKeyDraft}
                onChange={(event) => onApiKeyChange(event.target.value)}
                placeholder="Enter your Bright Data API key"
                className="h-12 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70 2xl:h-[52px] 2xl:px-4 2xl:text-base"
                autoComplete="off"
              />
              <span className="text-sm font-medium text-muted">
                You can find your API key in your{" "}
                <a
                  href="https://brightdata.com/cp"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 font-semibold text-[#2f80ed] transition hover:text-[#8cc7ff]"
                >
                  Bright Data dashboard
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
                .
              </span>
            </label>

            <div className="rounded-md border border-border bg-white/[0.018] px-4 py-4 2xl:px-5 2xl:py-5">
              <div className="grid gap-3 sm:grid-cols-[28px_minmax(0,1fr)]">
                <Info className="mt-0.5 h-5 w-5 text-[#2f80ed]" />
                <div>
                  <h3 className="text-sm font-bold text-[#d8dee8] 2xl:text-base">How it works</h3>
                  <p className="mt-2 max-w-[720px] text-sm leading-6 text-muted 2xl:text-base 2xl:leading-7">
                    Your API key is saved securely and used for LinkedIn and Indeed vacancy search on the server side.
                    <br />
                    The full key is fetched only when you reveal or copy it.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <p
                className={cn(
                  "flex items-center gap-3 text-sm font-semibold 2xl:text-base",
                  status === "error"
                    ? "text-[#ff7a7a]"
                    : settings.has_brightdata_api_key || copyStatus
                      ? "text-success"
                      : "text-muted",
                )}
              >
                {status === "error" ? <X className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />}
                {statusMessage}
              </p>
              <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                {settings.has_brightdata_api_key && (
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-12 w-full rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06] sm:w-auto 2xl:h-[52px] 2xl:text-sm"
                    disabled={status === "loading"}
                    onClick={onClear}
                  >
                    Clear key
                  </Button>
                )}
                <Button
                  type="button"
                  className="h-12 w-full rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12] sm:w-auto 2xl:h-[52px] 2xl:text-sm"
                  disabled={status === "loading" || !hasApiKeyDraft}
                  onClick={onSave}
                >
                  <Save className="h-4 w-4" />
                  {status === "loading" ? "Saving..." : "Save settings"}
                </Button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}

function LogsView({ logs, onClear }: { logs: AppLogEntry[]; onClear: () => void }) {
  const levelStyles: Record<AppLogLevel, string> = {
    info: "border-[#2f80ed]/35 bg-[#2f80ed]/12 text-[#8cc7ff]",
    success: "border-success/35 bg-success/12 text-success",
    warning: "border-[#ff9f1a]/35 bg-[#ff9f1a]/12 text-[#ffd08a]",
    error: "border-[#d94d4d]/45 bg-[#d94d4d]/13 text-[#ff8a8a]",
  };

  return (
    <section className="job-scroll flex h-screen min-w-0 flex-1 flex-col overflow-y-auto px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-4 flex shrink-0 flex-col gap-3 md:flex-row md:items-start md:justify-between 2xl:mb-5">
        <div>
          <h1 className="text-[24px] font-bold leading-tight tracking-normal text-white sm:text-[27px] 2xl:text-[31px]">
            Logs
          </h1>
          <p className="mt-1 text-[13px] text-muted 2xl:mt-1.5 2xl:text-base">Local application events and parser activity</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          className="h-10 w-full rounded-md border border-border bg-transparent px-4 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06] md:w-auto 2xl:h-11"
          disabled={logs.length === 0}
          onClick={onClear}
        >
          <Trash2 className="h-4 w-4" />
          Clear logs
        </Button>
      </header>

      <div className="panel flex min-h-[360px] max-w-[1120px] flex-1 flex-col overflow-hidden p-0">
        {logs.length === 0 ? (
          <div className="grid min-h-[360px] place-items-center px-4 text-center">
            <div>
              <FileText className="mx-auto h-8 w-8 text-muted" />
              <h2 className="mt-3 text-base font-bold text-white">No logs yet</h2>
              <p className="mt-1 max-w-[360px] text-sm leading-6 text-muted">
                Run a vacancy search or change settings to create log entries.
              </p>
            </div>
          </div>
        ) : (
          <div className="job-scroll min-h-0 flex-1 overflow-y-auto">
            {logs.map((log) => (
              <article key={log.id} className="border-b border-border px-4 py-3 last:border-0 2xl:px-5 2xl:py-4">
                <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn("inline-flex h-6 items-center rounded-md border px-2 text-[11px] font-bold uppercase", levelStyles[log.level])}>
                        {log.level}
                      </span>
                      <span className="text-xs font-bold text-[#d8dee8]">{log.area}</span>
                      <span className="text-xs text-muted">{formatLogTimestamp(log.timestamp)}</span>
                    </div>
                    <p className="mt-2 text-sm font-semibold leading-5 text-white 2xl:text-base">{log.message}</p>
                    {log.details && <p className="mt-1 whitespace-pre-wrap break-words font-mono text-xs leading-5 text-muted [overflow-wrap:anywhere]">{log.details}</p>}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function DashboardView({
  profile,
  jobs,
  applications,
  events,
  savedJobIds,
  isLoading,
  onStartSearch,
  onOpenJobs,
  onOpenJob,
  onToggleSavedJob,
  onOpenApplications,
  onOpenCalendar,
  onOpenAssistant,
  onOpenProfile,
}: {
  profile: CandidateProfile;
  jobs: Job[];
  applications: TrackedApplication[];
  events: ApplicationEvent[];
  savedJobIds: string[];
  isLoading: boolean;
  onStartSearch: () => void;
  onOpenJobs: () => void;
  onOpenJob: (jobId: string) => void;
  onToggleSavedJob: (jobId: string) => void;
  onOpenApplications: (applicationId?: string) => void;
  onOpenCalendar: () => void;
  onOpenAssistant: (prompt?: string, contextKind?: AssistantLaunch["contextKind"], contextId?: string) => void;
  onOpenProfile: () => void;
}) {
  const currentTime = useHydrationSafeCurrentTime();
  const now = currentTime?.getTime() ?? Number.NEGATIVE_INFINITY;
  const profileCompletion = getProfileCompletion(profile);
  const scoredJobs = jobs.filter(hasDisplayableMatch);
  const averageMatch = scoredJobs.length > 0
    ? Math.round(scoredJobs.reduce((total, job) => total + getDisplayMatch(job), 0) / scoredJobs.length)
    : 0;
  const recommendedJobs = [...jobs]
    .sort((left, right) => getDisplayMatch(right) - getDisplayMatch(left) || getJobPostedTime(right) - getJobPostedTime(left))
    .slice(0, 3);
  const upcomingEvents = sortApplicationEvents(events.filter((event) => (
    event.status === "scheduled" && new Date(event.startsAt).getTime() >= now
  )));
  const upcomingInterviews = upcomingEvents.filter((event) => event.type === "interview" || event.type === "screening");
  const nextEvent = upcomingEvents[0] ?? null;
  const nextEventApplication = nextEvent
    ? applications.find((application) => application.id === nextEvent.applicationId) ?? null
    : null;
  const offers = applications.filter((application) => application.status === "offer").length;
  const statusColors: Record<ApplicationStatus, string> = {
    draft: "#9f7aea",
    applied: "#ff5a00",
    interview: "#ff9f1a",
    assessment: "#2f80ed",
    offer: "#58d532",
    rejected: "#d94d4d",
  };
  let statusArcOffset = 0;
  const statusOverview = trackedApplicationStatuses.map((item) => {
    const count = applications.filter((application) => application.status === item.status).length;
    const arcPercentage = applications.length > 0 ? (count / applications.length) * 100 : 0;
    const arcOffset = statusArcOffset;
    statusArcOffset += arcPercentage;
    return {
      ...item,
      count,
      percentage: Math.round(arcPercentage),
      arcPercentage,
      arcOffset,
      color: statusColors[item.status],
    };
  });
  const visibleStatusCount = statusOverview.filter((item) => item.count > 0).length;
  const statCards = [
    {
      label: "Applications",
      value: applications.length.toString(),
      note: applications.length === 1 ? "Tracked application" : "Tracked applications",
      icon: FileText,
      tone: "orange",
      onClick: () => onOpenApplications(),
    },
    {
      label: "Interviews",
      value: upcomingInterviews.length.toString(),
      note: upcomingInterviews.length === 1 ? "Upcoming interview" : "Upcoming interviews",
      icon: CalendarDays,
      tone: "blue",
      onClick: onOpenCalendar,
    },
    {
      label: "Offers",
      value: offers.toString(),
      note: offers === 1 ? "Offer received" : "Offers received",
      icon: BriefcaseBusiness,
      tone: "green",
      onClick: () => onOpenApplications(),
    },
    {
      label: "Match Score",
      value: scoredJobs.length > 0 ? `${averageMatch}%` : "—",
      note: scoredJobs.length > 0 ? `Average across ${scoredJobs.length} scored job${scoredJobs.length === 1 ? "" : "s"}` : "No scored jobs yet",
      icon: Target,
      tone: "orange",
      onClick: onOpenJobs,
    },
  ];

  useEffect(() => {
    const openSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onStartSearch();
      }
    };
    window.addEventListener("keydown", openSearch);
    return () => window.removeEventListener("keydown", openSearch);
  }, [onStartSearch]);

  function openNextAssistantAction() {
    if (nextEvent && nextEventApplication && (nextEvent.type === "interview" || nextEvent.type === "screening")) {
      onOpenAssistant(assistantPrompts.prepareInterview, "application", nextEventApplication.id);
      return;
    }
    if (profileCompletion < 70) {
      onOpenAssistant(assistantPrompts.improveProfile, "profile");
      return;
    }
    onOpenAssistant("Review my current job search pipeline and give me the three highest-impact next actions.", "profile");
  }

  return (
    <section className="job-scroll flex h-screen min-w-0 flex-1 flex-col overflow-y-auto px-3 py-3 sm:px-4 xl:overflow-hidden xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-3 flex shrink-0 flex-col gap-3 md:flex-row md:items-start md:justify-between 2xl:mb-4 2xl:gap-4">
        <div>
          <DashboardGreeting name={profile.name} currentTime={currentTime} />
        </div>
      </header>

      <div className="grid shrink-0 gap-2.5 sm:grid-cols-2 xl:grid-cols-4 2xl:gap-3">
        {statCards.map((stat) => (
          <button
            key={stat.label}
            type="button"
            onClick={stat.onClick}
            className="panel group min-h-[108px] p-3 text-left transition hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/[0.035] 2xl:min-h-[126px] 2xl:p-4"
          >
            <div className="flex items-start gap-2.5 2xl:gap-3">
              <div className={cn(
                "grid h-9 w-9 shrink-0 place-items-center rounded-md 2xl:h-11 2xl:w-11",
                stat.tone === "green" ? "bg-success/20 text-success" : stat.tone === "blue" ? "bg-[#2f80ed]/20 text-[#79b9ff]" : "bg-accent/20 text-accent",
              )}>
                <stat.icon className="h-5 w-5 2xl:h-6 2xl:w-6" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs text-[#d6dbe4] 2xl:text-sm">{stat.label}</p>
                <p className="mt-1 text-[24px] font-bold leading-none 2xl:text-[28px]">{isLoading ? "—" : stat.value}</p>
                <p className="mt-1.5 line-clamp-2 text-xs text-muted 2xl:text-sm">{isLoading ? "Loading…" : stat.note}</p>
              </div>
              <ChevronRight className="h-4 w-4 text-muted transition group-hover:translate-x-0.5 group-hover:text-white" />
            </div>
            {stat.label === "Match Score" ? (
              <div className="mt-3 h-1.5 rounded-full bg-white/[0.06]">
                <div className="h-full rounded-full bg-gradient-to-r from-[#ff5a00] to-[#ff9f1a] transition-[width]" style={{ width: `${averageMatch}%` }} />
              </div>
            ) : null}
          </button>
        ))}
      </div>

      <div className="mt-2.5 grid shrink-0 gap-2.5 xl:min-h-0 xl:flex-1 xl:shrink xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.95fr)] 2xl:mt-3 2xl:gap-3">
        <div className="grid min-h-0 gap-2.5 xl:grid-rows-[minmax(0,1fr)_116px] 2xl:grid-rows-[minmax(0,1fr)_126px] 2xl:gap-3">
          <section className="panel flex min-h-[230px] flex-col overflow-hidden p-3 2xl:p-4">
            <div className="mb-2.5 flex items-center justify-between 2xl:mb-3">
              <div className="flex items-center gap-2.5 2xl:gap-3">
                <Star className="h-4 w-4 text-accent 2xl:h-5 2xl:w-5" />
                <h2 className="text-base font-bold 2xl:text-lg">Recommended Jobs</h2>
              </div>
              <button type="button" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent hover:text-[#ff7a35] 2xl:gap-2 2xl:text-sm" onClick={onOpenJobs}>
                View all jobs <ChevronRight className="h-4 w-4" />
              </button>
            </div>
            {recommendedJobs.length > 0 ? (
              <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-border">
                {recommendedJobs.map((job) => {
                  const isSaved = savedJobIds.includes(job.id);
                  return (
                    <div key={job.id} className="grid min-h-[58px] grid-cols-[minmax(0,1fr)_36px] items-center border-b border-border last:border-0 hover:bg-white/[0.025]">
                      <button
                        type="button"
                        className="grid min-w-0 grid-cols-[42px_minmax(0,1fr)_88px] items-center gap-2.5 px-3 py-2 text-left 2xl:grid-cols-[50px_minmax(0,1fr)_108px] 2xl:gap-3"
                        onClick={() => onOpenJob(job.id)}
                      >
                        <JobRoleIcon job={job} />
                        <div className="min-w-0">
                          <h3 className="truncate text-sm font-semibold 2xl:text-base">{job.title}</h3>
                          <p className="truncate text-xs text-muted">{job.company} · {job.location}</p>
                          <div className="mt-1 flex gap-1.5">
                            <span className="tag max-w-[96px] truncate">{job.type}</span>
                            <span className="tag max-w-[120px] truncate">Source: {getJobSourceLabel(job)}</span>
                          </div>
                        </div>
                        <div className="hidden text-left sm:block">
                          <p className={cn("text-xs font-semibold 2xl:text-sm", hasDisplayableMatch(job) ? "text-success" : "text-muted")}>{formatMatchValue(job)}{hasDisplayableMatch(job) ? " match" : ""}</p>
                          <p className="mt-0.5 truncate text-[11px] text-muted 2xl:mt-1 2xl:text-xs">{formatJobPosted(job.posted)}</p>
                        </div>
                      </button>
                      <button
                        type="button"
                        aria-label={isSaved ? `Remove ${job.title} from saved jobs` : `Save ${job.title}`}
                        title={isSaved ? "Remove from saved" : "Save job"}
                        onClick={() => onToggleSavedJob(job.id)}
                        className="grid h-9 w-9 place-items-center rounded-md text-muted transition hover:bg-white/[0.06] hover:text-accent"
                      >
                        <Bookmark className={cn("h-[18px] w-[18px]", isSaved && "fill-accent text-accent")} />
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <button type="button" onClick={onOpenJobs} className="grid min-h-0 flex-1 place-items-center rounded-md border border-dashed border-border px-4 text-center hover:border-accent/40 hover:bg-accent/[0.025]">
                <span>
                  <BriefcaseBusiness className="mx-auto h-7 w-7 text-muted" />
                  <span className="mt-2 block text-sm font-bold text-white">No jobs to recommend yet</span>
                  <span className="mt-1 block text-xs text-muted">Start a search to add vacancies.</span>
                </span>
              </button>
            )}
          </section>

          <section className="panel p-2.5 2xl:p-3">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2.5 2xl:gap-3">
                <Calendar className="h-4 w-4 text-muted" />
                <h2 className="text-sm font-bold 2xl:text-base">Next Event</h2>
              </div>
              <button type="button" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent hover:text-[#ff7a35] 2xl:gap-2 2xl:text-sm" onClick={onOpenCalendar}>
                View calendar <ChevronRight className="h-4 w-4" />
              </button>
            </div>
            {nextEvent ? (
              <button
                type="button"
                onClick={() => nextEventApplication ? onOpenApplications(nextEventApplication.id) : onOpenCalendar()}
                className="grid w-full gap-2 rounded-md border border-border px-3 py-2 text-left transition hover:border-white/20 hover:bg-white/[0.025] sm:grid-cols-[48px_minmax(0,1fr)_150px_auto] sm:items-center"
              >
                <div className="text-center">
                  <p className="text-[10px] font-bold uppercase text-accent">{new Date(nextEvent.startsAt).toLocaleDateString(undefined, { month: "short" })}</p>
                  <p className="text-lg font-bold leading-tight">{new Date(nextEvent.startsAt).getDate()}</p>
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{nextEvent.title}</p>
                  <p className="truncate text-xs text-muted">{nextEventApplication ? `${nextEventApplication.job.company} · ${nextEventApplication.job.title}` : getApplicationEventTypeLabel(nextEvent.type)}</p>
                </div>
                <div className="space-y-1 text-[11px] text-muted 2xl:text-xs">
                  <p className="flex items-center gap-1.5"><Calendar className="h-3.5 w-3.5" /> {formatApplicationEventDate(nextEvent.startsAt)}</p>
                  <p className="flex items-center gap-1.5"><CircleDot className="h-3.5 w-3.5" /> {formatApplicationEventTime(nextEvent.startsAt)}</p>
                </div>
                <span className="rounded-md border border-border px-2 py-1 text-[10px] font-bold text-[#cbd2dd]">{getApplicationEventTypeLabel(nextEvent.type)}</span>
              </button>
            ) : (
              <button type="button" onClick={onOpenCalendar} className="flex w-full items-center justify-between rounded-md border border-dashed border-border px-3 py-3 text-left text-xs text-muted hover:border-accent/40 hover:text-white">
                No upcoming events. Add one in Calendar.
                <Plus className="h-4 w-4" />
              </button>
            )}
          </section>
        </div>

        <aside className="grid min-h-0 gap-2.5 xl:grid-rows-[minmax(0,1fr)_178px] 2xl:grid-rows-[minmax(0,1fr)_190px] 2xl:gap-3">
          <section className="panel p-3 2xl:p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-bold 2xl:text-lg">Application Overview</h2>
              <span className="rounded-md border border-border px-2 py-1 text-[11px] text-muted 2xl:text-xs">All time</span>
            </div>
            <div className="grid items-center gap-3 sm:grid-cols-[116px_minmax(0,1fr)] 2xl:grid-cols-[132px_minmax(0,1fr)] 2xl:gap-4">
              <button
                type="button"
                aria-label={`Open ${applications.length} applications`}
                onClick={() => onOpenApplications()}
                className="group relative mx-auto h-[116px] w-[116px] rounded-full transition duration-200 hover:scale-[1.025] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 2xl:h-[132px] 2xl:w-[132px]"
              >
                <span className="absolute inset-1 rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.035),transparent_68%)] opacity-70 transition group-hover:opacity-100" />
                <svg viewBox="0 0 120 120" className="absolute inset-0 h-full w-full -rotate-90 overflow-visible drop-shadow-[0_4px_10px_rgba(0,0,0,0.24)]" aria-hidden="true">
                  <circle cx="60" cy="60" r="47" pathLength="100" fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="10" />
                  {statusOverview.map((item) => {
                    if (item.arcPercentage === 0) return null;
                    const segmentLength = visibleStatusCount > 1
                      ? Math.max(item.arcPercentage - 1.4, 0)
                      : item.arcPercentage;
                    return (
                      <circle
                        key={item.status}
                        cx="60"
                        cy="60"
                        r="47"
                        pathLength="100"
                        fill="none"
                        stroke={item.color}
                        strokeWidth="10"
                        strokeLinecap="round"
                        strokeDasharray={`${segmentLength} ${100 - segmentLength}`}
                        strokeDashoffset={-item.arcOffset}
                        className="transition-[stroke-width,opacity] duration-200 group-hover:opacity-95 group-hover:[stroke-width:11]"
                      />
                    );
                  })}
                </svg>
                <span className="absolute inset-[25px] grid place-items-center rounded-full border border-white/[0.06] bg-[#11171e]/95 shadow-[inset_0_1px_0_rgba(255,255,255,0.035),0_6px_18px_rgba(0,0,0,0.2)] 2xl:inset-[29px]">
                  <span className="text-center">
                    <span className="block text-[22px] font-bold leading-none tracking-tight text-white 2xl:text-[26px]">{isLoading ? "—" : applications.length}</span>
                    <span className="mt-1.5 block text-[10px] font-medium uppercase tracking-[0.14em] text-muted 2xl:text-[11px]">Total</span>
                  </span>
                </span>
              </button>
              <div className="space-y-2 2xl:space-y-2.5">
                {statusOverview.map((item) => (
                  <button key={item.status} type="button" onClick={() => onOpenApplications()} className="flex w-full items-center gap-2.5 rounded px-1 py-0.5 text-left text-[12px] hover:bg-white/[0.04] 2xl:gap-3 2xl:text-sm">
                    <span className="grid h-3 w-3 place-items-center rounded-full bg-white/[0.035] 2xl:h-3.5 2xl:w-3.5">
                      <span className="h-1.5 w-1.5 rounded-full 2xl:h-2 2xl:w-2" style={{ backgroundColor: item.color, boxShadow: `0 0 8px ${item.color}66` }} />
                    </span>
                    <span className="flex-1 text-muted">{item.label}</span>
                    <span className="text-[#cbd2dd]">{item.count} <span className="text-muted">({item.percentage}%)</span></span>
                  </button>
                ))}
              </div>
            </div>
            <button type="button" className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent hover:text-[#ff7a35] 2xl:gap-2 2xl:text-sm" onClick={() => onOpenApplications()}>
              Open applications <ChevronRight className="h-4 w-4" />
            </button>
          </section>

          <section className="panel p-2.5 2xl:p-3">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-bold 2xl:text-base">Next best action</h2>
              <Button variant="outline" size="sm" className="h-7 px-2 text-[11px]" onClick={() => onOpenAssistant()}>New Chat</Button>
            </div>
            <button type="button" onClick={openNextAssistantAction} className="flex w-full items-start gap-2.5 rounded-md border border-border p-2.5 text-left transition hover:border-accent/35 hover:bg-accent/[0.035]">
              <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent/20 text-accent">
                <Bot className="h-4 w-4" />
              </div>
              <span className="min-w-0">
                <span className="block text-xs font-bold text-white">
                  {nextEventApplication && (nextEvent?.type === "interview" || nextEvent?.type === "screening") ? "Prepare for your next interview" : profileCompletion < 70 ? "Strengthen your profile" : "Plan your next moves"}
                </span>
                <span className="mt-1 line-clamp-2 block text-[11px] leading-4 text-muted">
                  {nextEventApplication && (nextEvent?.type === "interview" || nextEvent?.type === "screening") ? `${nextEventApplication.job.company} · ${formatApplicationEventDate(nextEvent.startsAt)}` : profileCompletion < 70 ? `Your profile is ${profileCompletion}% complete.` : "Let the assistant review your pipeline and prioritize this week."}
                </span>
              </span>
              <Sparkles className="ml-auto h-4 w-4 shrink-0 text-accent" />
            </button>
            {profileCompletion < 100 ? (
              <button type="button" onClick={onOpenProfile} className="mt-2 flex w-full items-center gap-2 text-left text-[11px] text-muted hover:text-white">
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.07]"><span className="block h-full rounded-full bg-accent" style={{ width: `${profileCompletion}%` }} /></span>
                Profile {profileCompletion}%
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </section>
        </aside>
      </div>
    </section>
  );
}

function getProfileLinks(profile: CandidateProfile) {
  return [
    { label: "LinkedIn", value: profile.linkedin, icon: Linkedin },
    { label: "GitHub", value: profile.github, icon: Github },
    { label: "Portfolio", value: profile.portfolio, icon: FileText },
    { label: "Personal Site", value: profile.personal_site, icon: Globe },
  ].map((link) => ({ ...link, href: normalizeExternalUrl(link.value) }));
}

function ProfileView({
  profile,
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
    <section className="job-scroll flex h-screen min-w-0 flex-1 flex-col overflow-y-auto px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-4 flex shrink-0 flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-[24px] font-bold leading-tight tracking-normal text-white sm:text-[27px] 2xl:text-[31px]">My Profile</h1>
          <p className="mt-1 text-[13px] text-muted 2xl:mt-1.5 2xl:text-base">Your professional profile and job preferences</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenAssistant(assistantPrompts.improveProfile)}
            className="h-10 rounded-md border border-accent/40 bg-accent/[0.055] px-3 text-xs font-bold text-white hover:bg-accent/[0.11] 2xl:h-11 2xl:px-4 2xl:text-sm"
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
          profileResume={
            profile.resume_file_name && profile.resume_data_url
              ? {
                  fileName: profile.resume_file_name,
                  fileSize: profile.resume_file_size,
                  dataUrl: profile.resume_data_url,
                }
              : null
          }
        />
        <div className="grid gap-4 xl:grid-cols-2 2xl:gap-5">
          <ActivityPanel profile={profile} onEditProfile={onEditProfile} />
          <AiMatchProfilePanel profile={profile} onEditProfile={onEditProfile} />
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
        <PreferencesPanel profile={profile} onEditPreferences={onEditPreferences} />
        <DealbreakersPanel profile={profile} onEditDealbreakers={onEditDealbreakers} />
        <DocumentsPanel
          profile={profile}
          onAddDocument={onAddDocument}
          onEditDocument={onEditDocument}
          onDeleteDocument={onDeleteDocument}
        />
        <AdditionalNotesPanel profile={profile} onEditAdditionalNotes={onEditAdditionalNotes} />
        <ProfileCompletenessPanel profile={profile} />
        <ResumeTemplateManager apiBaseUrl={apiBaseUrl} />
      </div>
    </section>
  );
}

function ProfileHero({ profile, onEditProfile }: { profile: CandidateProfile; onEditProfile: () => void }) {
  const links = getProfileLinks(profile).filter((link) => hasProfileValue(link.value) && link.href);

  return (
    <section className="panel grid shrink-0 overflow-hidden md:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_410px]">
      <div className="relative flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:p-5 2xl:gap-5 2xl:p-6">
        <Button
          variant="ghost"
          className="absolute right-4 top-4 z-10 h-9 rounded-md border border-border bg-white/[0.03] px-3 text-xs font-bold text-[#e6ebf3] hover:bg-white/[0.075] sm:right-5 sm:top-5 2xl:h-10 2xl:px-4 2xl:text-[13px]"
          onClick={onEditProfile}
        >
          <Edit3 className="h-4 w-4" />
          Edit Profile
        </Button>
        <div className="relative h-24 w-24 shrink-0 overflow-hidden rounded-full bg-white/[0.06] ring-1 ring-white/10 2xl:h-28 2xl:w-28">
          <img
            src={profile.avatar_url || defaultCandidateProfile.avatar_url}
            alt={displayProfileValue(profile.name, "Profile avatar")}
            className="h-full w-full object-cover"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[24px] font-bold leading-tight text-white 2xl:text-[30px]">
              {displayProfileValue(profile.name, "Set up your profile")}
            </h2>
          </div>
          <p className="mt-2 text-base font-semibold text-[#d8dee8] 2xl:text-lg">
            {displayProfileValue(profile.current_role, "Add your current role")}
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-sm font-semibold text-muted 2xl:text-base">
            <span>Target role:</span>
            <button
              type="button"
              className="rounded-sm text-left font-bold text-accent transition hover:text-[#ff7a1a] focus:outline-none focus:ring-2 focus:ring-accent/45"
              onClick={onEditProfile}
            >
              {displayProfileValue(profile.desired_role, "Add the roles you want")}
            </button>
          </p>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[13px] font-medium text-muted 2xl:text-sm">
            <span className="inline-flex items-center gap-1.5"><MapPin className="h-4 w-4" /> {displayProfileValue(profile.location, "Add location")}</span>
            <span className="inline-flex items-center gap-1.5"><Globe className="h-4 w-4" /> {displayProfileValue(profile.work_format, "Remote, hybrid, onsite")}</span>
          </div>
          {hasProfileValue(profile.headline) ? (
            <p className="mt-4 max-w-[720px] text-[13px] leading-5 text-[#c6ceda] 2xl:text-sm 2xl:leading-6">
              {profile.headline}
            </p>
          ) : (
            <div className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-dashed border-white/[0.16] bg-white/[0.025] p-3">
              <p className="min-w-0 flex-1 text-[13px] leading-5 text-muted">
                Add a short summary so job matching can understand your background and goals.
              </p>
              <Button variant="ghost" className="h-8 rounded-md border border-border px-3 text-xs text-[#e6ebf3] hover:bg-white/[0.06]" onClick={onEditProfile}>
                <Plus className="h-4 w-4" />
                Add summary
              </Button>
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-border p-4 md:border-l md:border-t-0 sm:p-5 2xl:p-6">
        <h3 className="text-sm font-bold text-white 2xl:text-base">Contact & Links</h3>
        {links.length > 0 ? (
          <div className="mt-3 grid gap-2.5 2xl:gap-3">
            {links.map((link) => (
              <a
                key={link.label}
                href={link.href}
                target="_blank"
                rel="noreferrer"
                className="grid grid-cols-[36px_minmax(0,1fr)_16px] items-center gap-3 rounded-md border border-transparent p-1.5 transition hover:border-white/[0.10] hover:bg-white/[0.035]"
              >
                <span className="grid h-9 w-9 place-items-center rounded-md border border-border bg-white/[0.035] text-[#d8dee8]">
                  <link.icon className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] font-bold text-white 2xl:text-sm">{link.label}</span>
                  <span className="block truncate text-xs text-muted 2xl:text-[13px]">{link.value}</span>
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
    <div className={cn("rounded-md border border-dashed border-white/[0.16] bg-white/[0.025] p-3", className)}>
      <p className="text-sm font-bold text-white">{title}</p>
      <p className="mt-1 text-xs leading-5 text-muted 2xl:text-[13px]">{description}</p>
      <Button
        type="button"
        variant="ghost"
        className="mt-3 h-8 rounded-md border border-border bg-transparent px-3 text-xs text-[#e6ebf3] hover:bg-white/[0.06]"
        onClick={onAction}
      >
        <Plus className="h-4 w-4" />
        {action}
      </Button>
    </div>
  );
}

function ExperiencePanel({
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
  const hasResume = hasProfileValue(profile.resume_data_url) && hasProfileValue(profile.resume_file_name);

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-base font-bold 2xl:text-lg">Experience</h2>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-bold text-[#e6ebf3] transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-45 2xl:text-[13px]"
            onClick={onImportExperienceFromCv}
            disabled={!hasResume || isExperienceImporting}
            title={hasResume ? "Import experience from attached CV" : "Attach a CV first"}
          >
            <FileText className="h-4 w-4" />
            {isExperienceImporting ? "Importing..." : "Import from CV"}
          </button>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-bold text-accent transition hover:bg-accent/10 hover:text-[#ff7a1a] 2xl:text-[13px]"
            onClick={onAddExperience}
          >
            <Plus className="h-4 w-4" />
            Add Experience
          </button>
        </div>
      </div>
      {importMessage && (
        <p className="mt-3 text-xs font-semibold text-muted 2xl:text-[13px]">{importMessage}</p>
      )}
      {experienceItems.length > 0 ? (
        <div className="mt-4 space-y-4">
          {experienceItems.map((item) => (
            <article key={item.id} className="grid grid-cols-[40px_minmax(0,1fr)_auto] gap-3 rounded-md border border-border bg-white/[0.025] p-3">
              <span className="grid h-10 w-10 place-items-center rounded-md bg-white/[0.06] text-[#d8dee8]">
                <BriefcaseBusiness className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h3 className="text-sm font-bold text-white 2xl:text-base">{item.title}</h3>
                <p className="mt-0.5 text-[13px] font-semibold text-[#d8dee8] 2xl:text-sm">{item.company}</p>
                <p className="mt-1 text-xs text-muted 2xl:text-[13px]">
                  {[item.employment_type, item.location].filter(Boolean).join(" • ")}
                </p>
                <p className="mt-1 text-xs text-muted 2xl:text-[13px]">
                  {item.start_date || "Start date"} - {item.is_current ? "Present" : item.end_date || "End date"}
                </p>
                {item.description && (
                  <p className="mt-2 whitespace-pre-line text-[13px] leading-5 text-muted 2xl:text-sm">{item.description}</p>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  aria-label="Edit experience"
                  onClick={() => onEditExperience(item)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
                >
                  <Edit3 className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label="Delete experience"
                  onClick={() => onDeleteExperience(item.id)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#ff6b6b]/12 hover:text-[#ff7a7a]"
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

function SkillsPanel({
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
  const hasResume = hasProfileValue(profile.resume_data_url) && hasProfileValue(profile.resume_file_name);
  const skillPreviewLimit = 24;
  const visibleSkillItems = skillItems.slice(0, skillPreviewLimit);
  const hiddenSkillCount = Math.max(skillItems.length - visibleSkillItems.length, 0);

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
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-bold text-[#e6ebf3] transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-45 2xl:text-[13px]"
            onClick={onImportSkillsFromCv}
            disabled={!hasResume || isSkillsImporting}
            title={hasResume ? "Import skills from attached CV" : "Attach a CV first"}
          >
            <FileText className="h-4 w-4" />
            {isSkillsImporting ? "Importing..." : "Import from CV"}
          </button>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-bold text-accent transition hover:bg-accent/10 hover:text-[#ff7a1a] 2xl:text-[13px]"
            onClick={onEditSkills}
          >
            <Edit3 className="h-4 w-4" />
            Edit Skills
          </button>
        </div>
      </div>
      {importMessage && (
        <p className="mt-3 text-xs font-semibold text-muted 2xl:text-[13px]">{importMessage}</p>
      )}
      {skillItems.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {visibleSkillItems.map((skill) => (
            <span key={skill} className="inline-flex min-h-7 items-center rounded-md border border-border bg-white/[0.035] px-2.5 text-xs font-semibold text-[#d8dee8]">
              {skill}
            </span>
          ))}
          {hiddenSkillCount > 0 && (
            <button
              type="button"
              className="inline-flex min-h-7 items-center rounded-md border border-accent/35 bg-accent/10 px-2.5 text-xs font-bold text-[#ffd1b0] transition hover:border-accent/65 hover:bg-accent/15"
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

function EducationPanel({
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
  const hasResume = hasProfileValue(profile.resume_data_url) && hasProfileValue(profile.resume_file_name);

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-base font-bold 2xl:text-lg">Education & Certifications</h2>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-bold text-[#e6ebf3] transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-45 2xl:text-[13px]"
            onClick={onImportEducationFromCv}
            disabled={!hasResume || isEducationImporting}
            title={hasResume ? "Import education from attached CV" : "Attach a CV first"}
          >
            <FileText className="h-4 w-4" />
            {isEducationImporting ? "Importing..." : "Import from CV"}
          </button>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-bold text-accent transition hover:bg-accent/10 hover:text-[#ff7a1a] 2xl:text-[13px]"
            onClick={onAddEducation}
          >
            <Plus className="h-4 w-4" />
            Add Education
          </button>
        </div>
      </div>
      {importMessage && (
        <p className="mt-3 text-xs font-semibold text-muted 2xl:text-[13px]">{importMessage}</p>
      )}
      {educationItems.length > 0 ? (
        <div className="mt-4 space-y-4">
          {educationItems.map((item) => (
            <article key={item.id} className="grid grid-cols-[40px_minmax(0,1fr)_auto] gap-3 rounded-md border border-border bg-white/[0.025] p-3">
              <span className="grid h-10 w-10 place-items-center rounded-md bg-white/[0.06] text-[#d8dee8]">
                <GraduationCap className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h3 className="text-sm font-bold text-white 2xl:text-base">
                  {item.credential || "Education"}
                </h3>
                <p className="mt-0.5 text-[13px] font-semibold text-[#d8dee8] 2xl:text-sm">
                  {item.institution || "Institution not specified"}
                </p>
                {(item.field_of_study || item.location) && (
                  <p className="mt-1 text-xs text-muted 2xl:text-[13px]">
                    {[item.field_of_study, item.location].filter(Boolean).join(" • ")}
                  </p>
                )}
                {(item.start_date || item.end_date || item.is_current) && (
                  <p className="mt-1 text-xs text-muted 2xl:text-[13px]">
                    {item.start_date || "Start date"} - {item.is_current ? "Present" : item.end_date || "End date"}
                  </p>
                )}
                {item.description && (
                  <p className="mt-2 whitespace-pre-line text-[13px] leading-5 text-muted 2xl:text-sm">{item.description}</p>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  aria-label="Edit education"
                  onClick={() => onEditEducation(item)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
                >
                  <Edit3 className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label="Delete education"
                  onClick={() => onDeleteEducation(item.id)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#ff6b6b]/12 hover:text-[#ff7a7a]"
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

function DocumentsPanel({
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
          <h2 className="text-base font-bold 2xl:text-lg">Supporting Documents</h2>
          <p className="mt-1 text-xs font-medium text-muted 2xl:text-[13px]">Store separate English and German CVs, certificates and other reusable files.</p>
        </div>
        {documentItems.length > 0 && (
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-bold text-accent transition hover:bg-accent/10 hover:text-[#ff7a1a] 2xl:text-[13px]"
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
            <article key={item.id} className="grid grid-cols-[40px_minmax(0,1fr)_auto] gap-3 rounded-md border border-border bg-white/[0.025] p-3">
              <span className="grid h-10 w-10 place-items-center rounded-md bg-white/[0.06] text-[#d8dee8]">
                <FileText className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="min-w-0 text-sm font-bold text-white 2xl:text-base">{item.title || item.file_name}</h3>
                  <span className="rounded bg-white/[0.06] px-2 py-0.5 text-[11px] font-bold text-muted">{item.category}</span>
                  {item.category === "CV / Resume" && item.language ? <span className="rounded bg-[#2f80ed]/15 px-2 py-0.5 text-[11px] font-bold text-[#8cc7ff]">{item.language}</span> : null}
                </div>
                {item.issuer && (
                  <p className="mt-0.5 text-[13px] font-semibold text-[#d8dee8] 2xl:text-sm">{item.issuer}</p>
                )}
                <p className="mt-1 truncate text-xs text-muted 2xl:text-[13px]">
                  {item.file_name}
                  {item.file_size ? ` • ${item.file_size}` : ""}
                  {item.uploaded_at ? ` • ${formatProfileDate(item.uploaded_at)}` : ""}
                </p>
                {item.notes && (
                  <p className="mt-2 whitespace-pre-line text-[13px] leading-5 text-muted 2xl:text-sm">{item.notes}</p>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <a
                  aria-label="Download document"
                  href={item.data_url}
                  download={item.file_name || item.title}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
                >
                  <Download className="h-4 w-4" />
                </a>
                <button
                  type="button"
                  aria-label="Edit document"
                  onClick={() => onEditDocument(item)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
                >
                  <Edit3 className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label="Delete document"
                  onClick={() => onDeleteDocument(item.id)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition hover:bg-[#ff6b6b]/12 hover:text-[#ff7a7a]"
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

function ActivityPanel({ profile, onEditProfile }: { profile: CandidateProfile; onEditProfile: () => void }) {
  const completion = getProfileCompletion(profile);

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-bold 2xl:text-lg">Profile Snapshot</h2>
        <Button variant="ghost" size="sm" className="h-8 border border-border px-2 text-[11px] text-[#e6ebf3]" onClick={onEditProfile}>
          Edit
        </Button>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <MiniMetric icon={FileText} value={parseExperienceEntries(profile.experience).length.toString()} label="Experience" color="blue" />
        <MiniMetric icon={Star} value={parseProfileLines(profile.skills).length.toString()} label="Skills" color="orange" />
        <MiniMetric icon={Globe} value={getProfileLinks(profile).filter((link) => hasProfileValue(link.value) && link.href).length.toString()} label="Links" color="green" />
      </div>
      <div className="mt-4 rounded-md border border-border bg-white/[0.025] p-3">
        <div className="flex items-end gap-3">
          <p className="text-[28px] font-bold leading-none text-white">{completion}%</p>
          <p className="pb-1 text-xs font-medium text-muted">Profile completeness</p>
        </div>
        <div className="mt-3 h-2 rounded-full bg-white/[0.08]">
          <div className="h-full rounded-full bg-success" style={{ width: `${completion}%` }} />
        </div>
        <p className="mt-2 text-xs font-medium text-muted">
          {completion < 50 ? "Add basics, experience, and skills to improve matching." : "Profile has enough signal for better matching."}
        </p>
      </div>
    </section>
  );
}

function AiMatchProfilePanel({ profile, onEditProfile }: { profile: CandidateProfile; onEditProfile: () => void }) {
  const matchProfile = getAiMatchProfile(profile);
  const hasSignals = matchProfile.signals.length > 0;

  return (
    <section className="panel p-4 2xl:p-5">
      <div className="flex items-center gap-2.5">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-[#2f80ed]/20 text-sm font-black text-[#9cc6ff]">AI</span>
        <h2 className="text-base font-bold 2xl:text-lg">AI Match Profile</h2>
      </div>
      {hasSignals ? (
        <div className="mt-4 divide-y divide-border rounded-md border border-border">
          <AiProfileGroup title="Signals" icon={Check} iconClassName="text-success" items={matchProfile.signals} />
          {matchProfile.gaps.length > 0 ? (
            <AiProfileGroup title="Next gaps" icon={CircleDot} iconClassName="text-[#ffb020]" items={matchProfile.gaps} />
          ) : (
            <AiProfileGroup title="Ready for matching" icon={Check} iconClassName="text-success" items={["Profile has enough structured signal for job matching"]} />
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

function PreferencesPanel({
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
      <ProfileSectionHeader title="Job Preferences" action="Edit Preferences" onAction={onEditPreferences} />
      {preferenceSummary.length > 0 ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {preferenceSummary.map((group) => (
            <div
              key={group.label}
              className={cn(
                "rounded-md border border-border bg-white/[0.025] p-3",
                group.label === "Notes" && "md:col-span-2",
              )}
            >
              <p className="text-[11px] font-bold uppercase tracking-normal text-muted">{group.label}</p>
              {group.label === "Notes" ? (
                <p className="mt-2 whitespace-pre-line text-[13px] leading-5 text-[#d8dee8]">{group.values.join("\n")}</p>
              ) : (
                <div className="mt-2 flex flex-wrap gap-2">
                  {group.values.map((value) => (
                    <span key={value} className="inline-flex min-h-7 items-center rounded-md border border-border bg-white/[0.035] px-2.5 text-xs font-semibold text-[#d8dee8]">
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

function DealbreakersPanel({
  profile,
  onEditDealbreakers,
}: {
  profile: CandidateProfile;
  onEditDealbreakers: () => void;
}) {
  const dealbreakers = parseProfileLines(profile.dealbreakers);

  return (
    <section className="panel p-4 2xl:p-5">
      <ProfileSectionHeader title="Dealbreakers" action="Edit Dealbreakers" onAction={onEditDealbreakers} />
      {dealbreakers.length > 0 ? (
        <div className="mt-4 space-y-2.5">
          {dealbreakers.map((item) => (
            <p key={item} className="flex items-center gap-2 text-[13px] text-muted 2xl:text-sm">
              <Ban className="h-4 w-4 text-[#ff6b6b]" />
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

function AdditionalNotesPanel({
  profile,
  onEditAdditionalNotes,
}: {
  profile: CandidateProfile;
  onEditAdditionalNotes: () => void;
}) {
  return (
    <section className="panel p-4 2xl:p-5">
      <ProfileSectionHeader title="Additional Notes" action="Edit Notes" onAction={onEditAdditionalNotes} />
      {hasProfileValue(profile.additional_notes) ? (
        <div className="mt-4 whitespace-pre-line rounded-md border border-border bg-white/[0.025] p-3 text-[13px] leading-5 text-[#d8dee8]">
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

function ProfileCompletenessPanel({ profile }: { profile: CandidateProfile }) {
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
            {completedCount} of {completionItems.length} matching signals are complete
          </p>
        </div>
        <span className={cn(
          "inline-flex min-h-8 items-center self-start rounded-md border px-2.5 text-xs font-bold",
          missingItems.length === 0
            ? "border-success/40 bg-success/12 text-success"
            : "border-[#ffb020]/35 bg-[#ffb020]/10 text-[#ffd18a]",
        )}>
          {missingItems.length === 0 ? "Ready" : `${missingItems.length} next step${missingItems.length === 1 ? "" : "s"}`}
        </span>
      </div>
      {missingItems.length === 0 ? (
        <div className="mt-4 rounded-md border border-success/25 bg-success/10 p-3">
          <p className="text-sm font-bold text-white">Profile has enough signal for matching</p>
          <p className="mt-1 text-xs leading-5 text-muted 2xl:text-[13px]">
            Keep it fresh when your resume, target roles, or application constraints change.
          </p>
        </div>
      ) : (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {visibleMissingItems.map((item) => (
            <div key={item.label} className="flex items-start gap-2 rounded-md border border-border bg-white/[0.025] p-3">
              <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-[#ffb020]" />
              <div className="min-w-0">
                <p className="text-xs font-bold text-white 2xl:text-[13px]">{item.label}</p>
                <p className="mt-1 text-xs leading-5 text-muted">{item.action}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ProfileTextItem({ icon: Icon, text, compact = false }: { icon: typeof FileText; text: string; compact?: boolean }) {
  return (
    <div className={cn("grid gap-3 rounded-md border border-border bg-white/[0.025] p-3", compact ? "grid-cols-[24px_minmax(0,1fr)]" : "grid-cols-[32px_minmax(0,1fr)]")}>
      <Icon className="mt-0.5 h-5 w-5 text-[#d8dee8]" />
      <p className="min-w-0 text-[13px] leading-5 text-muted 2xl:text-sm">{text}</p>
    </div>
  );
}

function ProfileSectionHeader({ title, action, onAction }: { title: string; action: string; onAction: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-base font-bold 2xl:text-lg">{title}</h2>
      <button type="button" className="text-xs font-bold text-accent transition hover:text-[#ff7a1a] 2xl:text-[13px]" onClick={onAction}>
        {action}
      </button>
    </div>
  );
}

function MiniMetric({ icon: Icon, value, label, color }: { icon: typeof FileText; value: string; label: string; color: "blue" | "orange" | "green" }) {
  return (
    <div className="rounded-md border border-border bg-white/[0.025] p-3">
      <Icon className={cn("h-5 w-5", color === "blue" ? "text-[#2f80ed]" : color === "green" ? "text-success" : "text-accent")} />
      <p className="mt-2 text-xl font-bold leading-none text-white">{value}</p>
      <p className="mt-1 text-[11px] text-muted">{label}</p>
    </div>
  );
}

function AiProfileGroup({ title, items, icon: Icon, iconClassName }: { title: string; items: string[]; icon: typeof Check; iconClassName: string }) {
  return (
    <div className="p-3">
      <h3 className="text-[13px] font-bold text-white">{title}</h3>
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

function SkillsEditorDialog({
  skills,
  skillInput,
  status,
  message,
  onSkillInputChange,
  onAddSkill,
  onRemoveSkill,
  onClose,
  onSave,
}: {
  skills: string[];
  skillInput: string;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onSkillInputChange: (value: string) => void;
  onAddSkill: (skill: string) => void;
  onRemoveSkill: (skill: string) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const normalizedQuery = skillInput.trim().toLowerCase();
  const availableSuggestions = suggestedSkills.filter(
    (suggestion) =>
      !skills.some((skill) => skill.toLowerCase() === suggestion.toLowerCase()) &&
      (!normalizedQuery || suggestion.toLowerCase().includes(normalizedQuery)),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[720px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">Edit Skills</h2>
            <p className="mt-1 text-sm font-medium text-muted">Add skills one at a time, similar to LinkedIn.</p>
          </div>
          <button
            type="button"
            aria-label="Close skills editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <form
            className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]"
            onSubmit={(event) => {
              event.preventDefault();
              onAddSkill(skillInput);
            }}
          >
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Skill</span>
              <input
                value={skillInput}
                onChange={(event) => onSkillInputChange(event.target.value)}
                placeholder="e.g. Python, FastAPI, Docker"
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
              <span className="text-xs font-medium text-muted">Type to search suggestions, then click a chip or press Add.</span>
            </label>
            <Button
              type="submit"
              variant="ghost"
              className="mt-6 h-10 rounded-md border border-border bg-white/[0.035] px-4 text-[13px] text-[#e6ebf3] hover:bg-white/[0.07]"
            >
              <Plus className="h-4 w-4" />
              Add
            </Button>
          </form>

          <div className="mt-5">
            <h3 className="text-sm font-bold text-white">Selected skills</h3>
            {skills.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {skills.map((skill) => (
                  <span key={skill} className="inline-flex min-h-8 items-center gap-2 rounded-md border border-border bg-white/[0.04] px-2.5 text-xs font-semibold text-[#d8dee8]">
                    {skill}
                    <button
                      type="button"
                      aria-label={`Remove ${skill}`}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-muted transition hover:bg-white/[0.08] hover:text-white"
                      onClick={() => onRemoveSkill(skill)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-md border border-dashed border-white/[0.16] bg-white/[0.025] p-3 text-sm text-muted">
                No skills selected yet.
              </p>
            )}
          </div>

          <div className="mt-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-bold text-white">Suggested skills</h3>
              <p className="text-xs font-medium text-muted">
                {normalizedQuery ? `${availableSuggestions.length} matches` : `${availableSuggestions.length} available`}
              </p>
            </div>
            {availableSuggestions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {availableSuggestions.map((skill) => (
                  <button
                    key={skill}
                    type="button"
                    className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-border bg-white/[0.025] px-2.5 text-xs font-semibold text-[#d8dee8] transition hover:border-accent/60 hover:bg-accent/10 hover:text-white"
                    onClick={() => onAddSkill(skill)}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {skill}
                  </button>
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-md border border-dashed border-white/[0.16] bg-white/[0.025] p-3 text-sm text-muted">
                No suggestions match this search. Press Add to save it as a custom skill.
              </p>
            )}
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-sm font-semibold", status === "error" ? "text-[#ff7a7a]" : "text-muted")}>
            {message || `${skills.length} skills selected`}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12]"
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

function DealbreakersEditorDialog({
  dealbreakers,
  dealbreakerInput,
  status,
  message,
  onDealbreakerInputChange,
  onAddDealbreaker,
  onRemoveDealbreaker,
  onClearDealbreakers,
  onClose,
  onSave,
}: {
  dealbreakers: string[];
  dealbreakerInput: string;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onDealbreakerInputChange: (value: string) => void;
  onAddDealbreaker: (dealbreaker: string) => void;
  onRemoveDealbreaker: (dealbreaker: string) => void;
  onClearDealbreakers: () => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const normalizedQuery = dealbreakerInput.trim().toLowerCase();
  const availableSuggestions = suggestedDealbreakers.filter(
    (suggestion) =>
      !dealbreakers.some((dealbreaker) => dealbreaker.toLowerCase() === suggestion.toLowerCase()) &&
      (!normalizedQuery || suggestion.toLowerCase().includes(normalizedQuery)),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[720px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">Edit Dealbreakers</h2>
            <p className="mt-1 text-sm font-medium text-muted">Hard limits that should rule out a job match.</p>
          </div>
          <button
            type="button"
            aria-label="Close dealbreakers editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <form
            className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]"
            onSubmit={(event) => {
              event.preventDefault();
              onAddDealbreaker(dealbreakerInput);
            }}
          >
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Dealbreaker</span>
              <input
                value={dealbreakerInput}
                onChange={(event) => onDealbreakerInputChange(event.target.value)}
                placeholder="e.g. No onsite-only roles"
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
              <span className="text-xs font-medium text-muted">Leave the list empty when you have no hard limits.</span>
            </label>
            <Button
              type="submit"
              variant="ghost"
              className="mt-6 h-10 rounded-md border border-border bg-white/[0.035] px-4 text-[13px] text-[#e6ebf3] hover:bg-white/[0.07]"
            >
              <Plus className="h-4 w-4" />
              Add
            </Button>
          </form>

          <div className="mt-5 rounded-md border border-border bg-white/[0.025] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-bold text-white">Current hard limits</h3>
              <button
                type="button"
                className="inline-flex min-h-7 items-center rounded-md border border-border bg-white/[0.025] px-2.5 text-[11px] font-bold text-muted transition hover:border-accent/45 hover:bg-accent/10 hover:text-[#d8dee8]"
                onClick={onClearDealbreakers}
              >
                No dealbreakers
              </button>
            </div>
            {dealbreakers.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {dealbreakers.map((dealbreaker) => (
                  <span key={dealbreaker} className="inline-flex min-h-8 items-center gap-2 rounded-md border border-border bg-white/[0.04] px-2.5 text-xs font-semibold text-[#d8dee8]">
                    {dealbreaker}
                    <button
                      type="button"
                      aria-label={`Remove ${dealbreaker}`}
                      className="inline-flex h-5 w-5 items-center justify-center rounded text-muted transition hover:bg-white/[0.08] hover:text-white"
                      onClick={() => onRemoveDealbreaker(dealbreaker)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-md border border-dashed border-white/[0.16] bg-white/[0.025] p-3 text-sm text-muted">
                No hard limits are set. Save this empty list if every condition is flexible.
              </p>
            )}
          </div>

          <div className="mt-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-bold text-white">Suggested dealbreakers</h3>
              <p className="text-xs font-medium text-muted">
                {normalizedQuery ? `${availableSuggestions.length} matches` : `${availableSuggestions.length} available`}
              </p>
            </div>
            {availableSuggestions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {availableSuggestions.map((dealbreaker) => (
                  <button
                    key={dealbreaker}
                    type="button"
                    className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-border bg-white/[0.025] px-2.5 text-xs font-semibold text-[#d8dee8] transition hover:border-accent/60 hover:bg-accent/10 hover:text-white"
                    onClick={() => onAddDealbreaker(dealbreaker)}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {dealbreaker}
                  </button>
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-md border border-dashed border-white/[0.16] bg-white/[0.025] p-3 text-sm text-muted">
                No suggestions match this search. Press Add to save it as a custom hard limit.
              </p>
            )}
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-sm font-semibold", status === "error" ? "text-[#ff7a7a]" : "text-muted")}>
            {message || (dealbreakers.length === 0 ? "No dealbreakers set" : `${dealbreakers.length} dealbreakers selected`)}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12]"
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

function AdditionalNotesEditorDialog({
  notes,
  status,
  message,
  onChange,
  onClear,
  onClose,
  onSave,
}: {
  notes: string;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onChange: (value: string) => void;
  onClear: () => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[720px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">Edit Additional Notes</h2>
            <p className="mt-1 text-sm font-medium text-muted">Extra context for matching, applications, or future automation.</p>
          </div>
          <button
            type="button"
            aria-label="Close notes editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <label className="grid gap-2">
            <span className="text-xs font-bold text-[#d8dee8]">Notes</span>
            <textarea
              value={notes}
              onChange={(event) => onChange(event.target.value)}
              placeholder="Availability, motivation, personal positioning, application context, or anything that does not fit elsewhere..."
              rows={8}
              className="min-h-[220px] resize-none rounded-md border border-border bg-[#0d131a] px-3 py-2.5 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
            />
            <span className="text-xs font-medium text-muted">Leave empty if there is no extra context to add.</span>
          </label>
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              className="inline-flex min-h-8 items-center rounded-md border border-border bg-white/[0.025] px-3 text-xs font-bold text-muted transition hover:border-accent/45 hover:bg-accent/10 hover:text-[#d8dee8]"
              onClick={onClear}
            >
              Clear notes
            </button>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-sm font-semibold", status === "error" ? "text-[#ff7a7a]" : "text-muted")}>
            {message || (notes.trim() ? "Notes ready to save" : "No notes set")}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12]"
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

function ExperienceEditorDialog({
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
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[760px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">
              {isEditMode ? "Edit Experience" : "Add Experience"}
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              {isEditMode ? "Update this role, internship, freelance project, or relevant IT project." : "Add one role, internship, freelance project, or relevant IT project."}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close experience editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Role title</span>
              <input
                value={experience.title}
                onChange={(event) => onChange("title", event.target.value)}
                placeholder="e.g. Junior Python Developer"
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Company / project</span>
              <input
                value={experience.company}
                onChange={(event) => onChange("company", event.target.value)}
                placeholder="Company name or project name"
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Employment type</span>
              <select
                value={experience.employment_type}
                onChange={(event) => onChange("employment_type", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
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
              <span className="text-xs font-bold text-[#d8dee8]">Location</span>
              <input
                value={experience.location}
                onChange={(event) => onChange("location", event.target.value)}
                placeholder="Remote, Zurich, Switzerland..."
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Start date</span>
              <input
                type="month"
                value={experience.start_date}
                onChange={(event) => onChange("start_date", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">End date</span>
              <input
                type="month"
                value={experience.end_date}
                disabled={experience.is_current}
                onChange={(event) => onChange("end_date", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none disabled:opacity-45 focus:border-accent/70"
              />
            </label>

            <label className="flex items-start gap-3 rounded-md border border-border bg-white/[0.025] p-3 md:col-span-2">
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
                <span className="block text-sm font-bold text-white">I currently work here</span>
                <span className="mt-1 block text-xs text-muted">End date will be shown as Present.</span>
              </span>
            </label>

            <label className="grid gap-2 md:col-span-2">
              <span className="text-xs font-bold text-[#d8dee8]">Description</span>
              <textarea
                value={experience.description}
                onChange={(event) => onChange("description", event.target.value)}
                placeholder="What did you build, support, automate, or improve?"
                rows={5}
                className="min-h-[128px] resize-none rounded-md border border-border bg-[#0d131a] px-3 py-2.5 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-sm font-semibold", status === "error" ? "text-[#ff7a7a]" : "text-muted")}>
            {message || "Role title and company are required"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12]"
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

function EducationEditorDialog({
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
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[760px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">
              {isEditMode ? "Edit Education" : "Add Education"}
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              {isEditMode ? "Update this degree, course, certification, or training." : "Add one degree, course, certification, or training."}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close education editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Institution</span>
              <input
                value={education.institution}
                onChange={(event) => onChange("institution", event.target.value)}
                placeholder="University, school, provider..."
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Credential</span>
              <input
                value={education.credential}
                onChange={(event) => onChange("credential", event.target.value)}
                placeholder="Bachelor, certificate, course name..."
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Field of study</span>
              <input
                value={education.field_of_study}
                onChange={(event) => onChange("field_of_study", event.target.value)}
                placeholder="Computer Science, Data Analytics..."
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Location</span>
              <input
                value={education.location}
                onChange={(event) => onChange("location", event.target.value)}
                placeholder="Remote, Zurich, Switzerland..."
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Start date</span>
              <input
                type="month"
                value={education.start_date}
                onChange={(event) => onChange("start_date", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">End date</span>
              <input
                type="month"
                value={education.end_date}
                disabled={education.is_current}
                onChange={(event) => onChange("end_date", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none disabled:opacity-45 focus:border-accent/70"
              />
            </label>

            <label className="flex items-start gap-3 rounded-md border border-border bg-white/[0.025] p-3 md:col-span-2">
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
                <span className="block text-sm font-bold text-white">I currently study here</span>
                <span className="mt-1 block text-xs text-muted">End date will be shown as Present.</span>
              </span>
            </label>

            <label className="grid gap-2 md:col-span-2">
              <span className="text-xs font-bold text-[#d8dee8]">Details</span>
              <textarea
                value={education.description}
                onChange={(event) => onChange("description", event.target.value)}
                placeholder="Relevant coursework, honors, thesis, certification ID, or training details..."
                rows={5}
                className="min-h-[128px] resize-none rounded-md border border-border bg-[#0d131a] px-3 py-2.5 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-sm font-semibold", status === "error" ? "text-[#ff7a7a]" : "text-muted")}>
            {message || "Institution and credential are required"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12]"
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

function DocumentEditorDialog({
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
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[720px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">
              {isEditMode ? "Edit Document" : "Add Document"}
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">Label a reusable personal file and attach it to your profile library.</p>
          </div>
          <button
            type="button"
            aria-label="Close document editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Document title</span>
              <input
                value={document.title}
                onChange={(event) => onChange("title", event.target.value)}
                placeholder="Main CV, Swiss work permit, diploma..."
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Type</span>
              <select
                value={document.category}
                onChange={(event) => onChange("category", event.target.value)}
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
              >
                {documentCategories.map((category) => (
                  <option key={category}>{category}</option>
                ))}
              </select>
            </label>

            {isGeneratedDocumentSource ? (
              <label className="grid gap-2 md:col-span-2">
                <span className="text-xs font-bold text-[#d8dee8]">Document language</span>
                <select
                  value={document.language}
                  onChange={(event) => onChange("language", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                >
                  <option value="">Select language</option>
                  <option value="English">English</option>
                  <option value="German">German</option>
                </select>
                <span className="text-[11px] leading-4 text-muted">Add separate English and German DOCX versions so Rufina can select the right one for each vacancy.</span>
              </label>
            ) : null}

            <label className="grid gap-2 md:col-span-2">
              <span className="text-xs font-bold text-[#d8dee8]">Issued by / source</span>
              <input
                value={document.issuer}
                onChange={(event) => onChange("issuer", event.target.value)}
                placeholder="University, certification provider, employer, immigration office..."
                className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>

            <div className="rounded-md border border-border bg-white/[0.025] p-3 md:col-span-2">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="text-sm font-bold text-white">Attached file</p>
                  <p className="mt-1 truncate text-xs text-muted">
                    {document.file_name ? `${document.file_name}${document.file_size ? ` • ${document.file_size}` : ""}` : isGeneratedDocumentSource ? "DOCX under 5MB — its design will be preserved" : "PDF, DOC, DOCX, PNG, JPG, or WebP under 5MB"}
                  </p>
                </div>
                <label className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-md border border-border bg-white/[0.035] px-3 text-xs font-semibold text-[#e6ebf3] transition hover:bg-white/[0.07]">
                  <Upload className="h-4 w-4" />
                  {document.file_name ? "Replace file" : "Attach file"}
                  <input
                    type="file"
                    accept={isGeneratedDocumentSource ? ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" : ".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg,image/webp"}
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
              <span className="text-xs font-bold text-[#d8dee8]">Notes</span>
              <textarea
                value={document.notes}
                onChange={(event) => onChange("notes", event.target.value)}
                placeholder="When to use it, expiration date, original language, or anything important..."
                rows={4}
                className="min-h-[112px] resize-none rounded-md border border-border bg-[#0d131a] px-3 py-2.5 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-sm font-semibold", status === "error" ? "text-[#ff7a7a]" : "text-muted")}>
            {message || "Title and file are required"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12]"
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

function PreferencesEditorDialog({
  preferences,
  inputs,
  status,
  message,
  onChange,
  onInputChange,
  onAddListItem,
  onRemoveListItem,
  onToggleOption,
  onSetAny,
  onClose,
  onSave,
}: {
  preferences: JobPreferences;
  inputs: PreferenceInputs;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onChange: <Field extends keyof JobPreferences>(
    field: Field,
    value: JobPreferences[Field],
  ) => void;
  onInputChange: (field: PreferenceListField, value: string) => void;
  onAddListItem: (field: PreferenceListField) => void;
  onRemoveListItem: (field: PreferenceListField, value: string) => void;
  onToggleOption: (
    field: PreferenceToggleField,
    value: string,
  ) => void;
  onSetAny: (field: PreferenceAnyField) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[880px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">Edit Job Preferences</h2>
            <p className="mt-1 text-sm font-medium text-muted">Define the roles and conditions that should guide search, matching, and recommendations.</p>
          </div>
          <button
            type="button"
            aria-label="Close preferences editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="grid gap-4">
            {(Object.keys(preferenceListLabels) as PreferenceListField[]).map((field) => (
              <PreferenceListEditor
                key={field}
                field={field}
                values={preferences[field]}
                inputValue={inputs[field]}
                isAny={preferences.no_preference.includes(field)}
                onInputChange={onInputChange}
                onAdd={onAddListItem}
                onRemove={onRemoveListItem}
                onSetAny={onSetAny}
              />
            ))}

            <PreferenceToggleGroup
              title="Seniority"
              field="seniority"
              options={preferenceOptions.seniority}
              selectedValues={preferences.seniority}
              isAny={preferences.no_preference.includes("seniority")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />
            <PreferenceToggleGroup
              title="Work format"
              field="work_formats"
              options={preferenceOptions.work_formats}
              selectedValues={preferences.work_formats}
              isAny={preferences.no_preference.includes("work_formats")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />
            <PreferenceToggleGroup
              title="Employment type"
              field="employment_types"
              options={preferenceOptions.employment_types}
              selectedValues={preferences.employment_types}
              isAny={preferences.no_preference.includes("employment_types")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />
            <PreferenceToggleGroup
              title="Company size"
              field="company_sizes"
              options={preferenceOptions.company_sizes}
              selectedValues={preferences.company_sizes}
              isAny={preferences.no_preference.includes("company_sizes")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />
            <PreferenceToggleGroup
              title="Search priority"
              field="priorities"
              options={preferenceOptions.priorities}
              selectedValues={preferences.priorities}
              isAny={preferences.no_preference.includes("priorities")}
              onToggle={onToggleOption}
              onSetAny={onSetAny}
            />

            <div className="grid gap-4 rounded-md border border-border bg-white/[0.025] p-3 sm:grid-cols-[130px_minmax(0,1fr)]">
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Currency</span>
                <select
                  value={preferences.salary_currency}
                  onChange={(event) => onChange("salary_currency", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                >
                  {["CHF", "EUR", "USD", "GBP"].map((currency) => (
                    <option key={currency}>{currency}</option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Minimum salary</span>
                <input
                  inputMode="numeric"
                  value={preferences.salary_min}
                  disabled={preferences.no_preference.includes("salary")}
                  onChange={(event) => onChange("salary_min", event.target.value.replace(/[^\d\s.,']/g, ""))}
                  placeholder="90000"
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 disabled:opacity-45 focus:border-accent/70"
                />
              </label>
              <button
                type="button"
                className={cn(
                  "inline-flex min-h-9 items-center justify-center rounded-md border px-3 text-xs font-bold transition sm:col-span-2",
                  preferences.no_preference.includes("salary")
                    ? "border-accent/65 bg-accent/14 text-white"
                    : "border-border bg-white/[0.025] text-[#d8dee8] hover:border-accent/45 hover:bg-accent/10",
                )}
                onClick={() => onSetAny("salary")}
              >
                No salary preference
              </button>
            </div>

            <div className="grid gap-3 rounded-md border border-border bg-white/[0.025] p-3">
              <span className="text-xs font-bold text-[#d8dee8]">Work authorization</span>
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_180px]">
                <select
                  value={preferences.work_authorization}
                  disabled={preferences.no_preference.includes("work_authorization")}
                  onChange={(event) => onChange("work_authorization", event.target.value)}
                  className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none disabled:opacity-45 focus:border-accent/70"
                >
                  <option value="">Not specified</option>
                  {preferenceOptions.work_authorization.map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
                <button
                  type="button"
                  className={cn(
                    "inline-flex min-h-10 items-center justify-center rounded-md border px-3 text-xs font-bold transition",
                    preferences.no_preference.includes("work_authorization")
                      ? "border-accent/65 bg-accent/14 text-white"
                      : "border-border bg-white/[0.025] text-[#d8dee8] hover:border-accent/45 hover:bg-accent/10",
                  )}
                  onClick={() => onSetAny("work_authorization")}
                >
                  No preference
                </button>
              </div>
              {preferences.work_authorization === "Swiss permit" && !preferences.no_preference.includes("work_authorization") ? (
                <label className="grid gap-2">
                  <span className="text-xs font-bold text-[#d8dee8]">Swiss permit status</span>
                  <select
                    value={preferences.swiss_permit_status}
                    onChange={(event) => onChange("swiss_permit_status", event.target.value)}
                    className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none focus:border-accent/70"
                  >
                    <option value="">Select permit status</option>
                    {preferenceOptions.swiss_permit_status.map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                </label>
              ) : null}
            </div>

            <label className="grid gap-2">
              <span className="text-xs font-bold text-[#d8dee8]">Notes</span>
              <textarea
                value={preferences.notes}
                onChange={(event) => onChange("notes", event.target.value)}
                placeholder="Availability, preferred tech stack, relocation timing, or other matching context..."
                rows={4}
                className="min-h-[112px] resize-none rounded-md border border-border bg-[#0d131a] px-3 py-2.5 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
              />
            </label>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-sm font-semibold", status === "error" ? "text-[#ff7a7a]" : "text-muted")}>
            {message || "Empty preferences stay hidden"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12]"
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

function PreferenceListEditor({
  field,
  values,
  inputValue,
  isAny,
  onInputChange,
  onAdd,
  onRemove,
  onSetAny,
}: {
  field: PreferenceListField;
  values: string[];
  inputValue: string;
  isAny: boolean;
  onInputChange: (field: PreferenceListField, value: string) => void;
  onAdd: (field: PreferenceListField) => void;
  onRemove: (field: PreferenceListField, value: string) => void;
  onSetAny: (field: PreferenceAnyField) => void;
}) {
  const config = preferenceListLabels[field];
  const suggestionListId = `${field}-suggestions`;

  return (
    <div className="rounded-md border border-border bg-white/[0.025] p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-bold text-[#d8dee8]">{config.label}</p>
        <button
          type="button"
          className={cn(
            "inline-flex min-h-7 items-center rounded-md border px-2.5 text-[11px] font-bold transition",
            isAny
              ? "border-accent/65 bg-accent/14 text-white"
              : "border-border bg-white/[0.025] text-muted hover:border-accent/45 hover:bg-accent/10 hover:text-[#d8dee8]",
          )}
          onClick={() => onSetAny(field)}
        >
          No preference
        </button>
      </div>
      <div className="mt-2 flex gap-2">
        <input
          value={inputValue}
          disabled={isAny}
          list={suggestionListId}
          onChange={(event) => onInputChange(field, event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              onAdd(field);
            }
          }}
          placeholder={config.placeholder}
          className="h-9 min-w-0 flex-1 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 disabled:opacity-45 focus:border-accent/70"
        />
        <datalist id={suggestionListId}>
          {preferenceSuggestions[field].map((suggestion) => (
            <option key={suggestion} value={suggestion} />
          ))}
        </datalist>
        <button
          type="button"
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border text-[#e6ebf3] transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-45"
          onClick={() => onAdd(field)}
          disabled={isAny}
          aria-label={`Add ${config.label.toLowerCase()}`}
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
      {isAny && (
        <p className="mt-3 rounded-md border border-accent/25 bg-accent/10 px-3 py-2 text-xs font-semibold text-[#ffd1b0]">
          Any {config.label.toLowerCase()} is acceptable.
        </p>
      )}
      {values.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {values.map((value) => (
            <button
              key={value}
              type="button"
              className="inline-flex min-h-7 items-center gap-1.5 rounded-md border border-border bg-white/[0.04] px-2.5 text-xs font-semibold text-[#d8dee8] transition hover:border-[#ff6b6b]/50 hover:text-white"
              onClick={() => onRemove(field, value)}
            >
              {value}
              <X className="h-3.5 w-3.5 text-muted" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PreferenceToggleGroup({
  title,
  field,
  options,
  selectedValues,
  isAny,
  onToggle,
  onSetAny,
  className,
}: {
  title: string;
  field: PreferenceToggleField;
  options: string[];
  selectedValues: string[];
  onToggle: (
    field: PreferenceToggleField,
    value: string,
  ) => void;
  isAny: boolean;
  onSetAny: (field: PreferenceAnyField) => void;
  className?: string;
}) {
  return (
    <div className={cn("rounded-md border border-border bg-white/[0.025] p-3", className)}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-bold text-[#d8dee8]">{title}</p>
        <button
          type="button"
          className={cn(
            "inline-flex min-h-7 items-center rounded-md border px-2.5 text-[11px] font-bold transition",
            isAny
              ? "border-accent/65 bg-accent/14 text-white"
              : "border-border bg-white/[0.025] text-muted hover:border-accent/45 hover:bg-accent/10 hover:text-[#d8dee8]",
          )}
          onClick={() => onSetAny(field)}
        >
          No preference
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map((option) => {
          const isSelected = selectedValues.includes(option) && !isAny;
          return (
            <button
              key={option}
              type="button"
              className={cn(
                "inline-flex min-h-8 items-center rounded-md border px-2.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-45",
                isSelected
                  ? "border-accent/65 bg-accent/14 text-white"
                  : "border-border bg-white/[0.025] text-[#d8dee8] hover:border-accent/45 hover:bg-accent/10",
              )}
              disabled={isAny}
              onClick={() => onToggle(field, option)}
            >
              {option}
            </button>
          );
        })}
      </div>
      {isAny && (
        <p className="mt-3 rounded-md border border-accent/25 bg-accent/10 px-3 py-2 text-xs font-semibold text-[#ffd1b0]">
          Any {title.toLowerCase()} is acceptable.
        </p>
      )}
    </div>
  );
}

function ProfileEditorDialog({
  profile,
  status,
  message,
  onChange,
  onClose,
  onSave,
}: {
  profile: CandidateProfile;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onChange: <Field extends keyof CandidateProfile>(
    field: Field,
    value: CandidateProfile[Field],
  ) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const fields: Array<{
    field: keyof CandidateProfile;
    label: string;
    placeholder: string;
    type?: "input" | "textarea";
  }> = [
    { field: "name", label: "Name", placeholder: "Your full name" },
    { field: "current_role", label: "Current role", placeholder: "Frontend Engineer, Product Manager, Student..." },
    { field: "desired_role", label: "Target role", placeholder: "Roles you want to apply for" },
    { field: "location", label: "Location", placeholder: "City, country, timezone, or remote" },
    { field: "work_format", label: "Work format", placeholder: "Remote, hybrid, onsite, relocation" },
    { field: "headline", label: "Headline / summary", placeholder: "Short positioning statement", type: "textarea" },
    { field: "linkedin", label: "LinkedIn", placeholder: "linkedin.com/in/username" },
    { field: "github", label: "GitHub", placeholder: "github.com/username" },
    { field: "portfolio", label: "Portfolio", placeholder: "portfolio.com" },
    { field: "personal_site", label: "Personal site", placeholder: "your-site.com" },
  ];

  function handleAvatarFile(file: File | undefined) {
    if (!file) return;

    if (file.size > 1_000_000) {
      window.alert("Avatar image must be under 1MB.");
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        onChange("avatar_url", reader.result);
      }
    };
    reader.readAsDataURL(file);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[820px] flex-col overflow-hidden border-white/[0.11] bg-[#111820]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-white 2xl:text-[24px]">Edit Profile</h2>
            <p className="mt-1 text-sm font-medium text-muted">Add the details you want job matching and applications to use.</p>
          </div>
          <button
            type="button"
            aria-label="Close profile editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="mb-5 flex flex-col gap-4 rounded-md border border-border bg-white/[0.025] p-4 sm:flex-row sm:items-center">
            <img
              src={profile.avatar_url || defaultCandidateProfile.avatar_url}
              alt=""
              className="h-20 w-20 shrink-0 rounded-full object-cover ring-1 ring-white/10"
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-white">Avatar</p>
              <p className="mt-1 text-xs leading-5 text-muted">Default is the pug image. Upload PNG, JPG, WebP, GIF, or SVG under 1MB.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <label className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-md border border-border bg-white/[0.035] px-3 text-xs font-semibold text-[#e6ebf3] transition hover:bg-white/[0.07]">
                  <Upload className="h-4 w-4" />
                  Change Avatar
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
                    className="hidden"
                    onChange={(event) => handleAvatarFile(event.target.files?.[0])}
                  />
                </label>
                <button
                  type="button"
                  className="inline-flex h-9 items-center justify-center rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#e6ebf3] transition hover:bg-white/[0.06]"
                  onClick={() => onChange("avatar_url", defaultCandidateProfile.avatar_url)}
                >
                  Use Default
                </button>
              </div>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {fields.map((item) => (
              <label
                key={item.field}
                className={cn("grid gap-2", item.type === "textarea" && "md:col-span-2")}
              >
                <span className="text-xs font-bold text-[#d8dee8]">{item.label}</span>
                {item.type === "textarea" ? (
                  <textarea
                    value={profile[item.field]}
                    onChange={(event) => onChange(item.field, event.target.value)}
                    placeholder={item.placeholder}
                    rows={4}
                    className="min-h-[112px] resize-none rounded-md border border-border bg-[#0d131a] px-3 py-2.5 text-sm font-semibold leading-5 text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  />
                ) : (
                  <input
                    value={profile[item.field]}
                    onChange={(event) => onChange(item.field, event.target.value)}
                    placeholder={item.placeholder}
                    className="h-10 rounded-md border border-border bg-[#0d131a] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/70 focus:border-accent/70"
                  />
                )}
              </label>
            ))}
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-sm font-semibold", status === "error" ? "text-[#ff7a7a]" : "text-muted")}>
            {message || "Empty fields stay hidden on the profile page"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#e6ebf3] hover:bg-white/[0.06]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#ff3d00] px-7 text-[13px] text-white shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#ff6a14] hover:to-[#ff4a12]"
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

function AppSidebar({
  activeView,
  onChangeView,
  profile,
  showLogs,
}: {
  activeView: View;
  onChangeView: (view: View) => void;
  profile: CandidateProfile;
  showLogs: boolean;
}) {
  const visibleNavItems = showLogs
    ? [...navItems, { label: "Logs", icon: FileText, href: "#logs", view: "Logs" as const }]
    : navItems;

  return (
    <aside className="app-sidebar hidden h-screen w-[190px] shrink-0 overflow-y-auto border-r border-border bg-white/[0.025] px-2.5 py-4 lg:flex lg:flex-col 2xl:w-[220px] 2xl:px-3 2xl:py-5">
      <div className="app-sidebar-brand mb-5 flex items-center gap-2 px-2 2xl:mb-7 2xl:gap-2.5">
        <img
          src="/brand/rufina-mark.png"
          alt=""
          className="app-sidebar-mark h-[42px] w-[42px] object-contain 2xl:h-12 2xl:w-12"
          aria-hidden="true"
        />
        <div className="min-w-0">
          <p className="text-[19px] font-extrabold leading-none tracking-[-0.025em] text-[#f5f2f0] 2xl:text-[22px]">Rufina</p>
          <p className="mt-1.5 whitespace-nowrap text-[10px] font-medium leading-none tracking-[0.015em] text-[#aeb5c2] 2xl:text-[11px]">
            Career Assistant
          </p>
        </div>
      </div>

      <nav className="app-sidebar-nav space-y-1.5 2xl:space-y-2">
        {visibleNavItems.map((item) => (
          <a
            href={item.href}
            key={item.label}
            onClick={() => {
              if (item.view) {
                onChangeView(item.view);
              }
            }}
            className={cn(
              "app-sidebar-nav-item group flex h-10 w-full items-center gap-2.5 rounded-md px-3 text-left text-[14px] text-[#d9dee7] transition 2xl:h-11 2xl:gap-3 2xl:px-4 2xl:text-[15px]",
              item.view === activeView || (activeView === "ApplicationWorkspace" && item.view === "Applications")
                ? "border border-white/[0.12] bg-white/10 text-white shadow-[inset_4px_0_0_#ff5a00]"
                : item.view
                  ? "hover:bg-white/[0.055] hover:text-white"
                  : "cursor-default opacity-70",
            )}
          >
            <item.icon className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
            <span>{item.label}</span>
          </a>
        ))}
      </nav>

      <div className="app-sidebar-footer mt-auto border-t border-border pt-3 2xl:pt-4">
        <a
          href="#profile"
          onClick={() => onChangeView("Profile")}
          className={cn(
            "app-sidebar-profile mb-2 flex items-center gap-1.5 rounded-md px-1.5 py-1.5 text-left transition hover:bg-white/[0.055] 2xl:mb-3 2xl:gap-2",
            activeView === "Profile" && "border border-white/[0.12] bg-white/10 shadow-[inset_4px_0_0_#ff5a00]",
          )}
        >
          <img
            src={profile.avatar_url || defaultCandidateProfile.avatar_url}
            alt=""
            className="h-8 w-8 shrink-0 rounded-full object-cover 2xl:h-8 2xl:w-8"
            aria-hidden="true"
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold leading-tight text-white 2xl:text-[13px]">
              {displayProfileFirstName(profile.name, "Set up profile")}
            </p>
            <p className="truncate text-[10px] leading-tight text-muted 2xl:text-[11px]">
              {displayProfileValue(profile.current_role, "Add your role")}
            </p>
          </div>
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted 2xl:h-4 2xl:w-4" />
        </a>
        <a
          href="#settings"
          onClick={() => onChangeView("Settings")}
          className={cn(
            "app-sidebar-settings flex h-10 items-center gap-2.5 rounded-md px-3 text-sm text-muted transition hover:bg-white/[0.055] hover:text-white 2xl:h-11 2xl:gap-3 2xl:text-base",
            activeView === "Settings" && "border border-white/[0.12] bg-white/10 text-white shadow-[inset_4px_0_0_#ff5a00]",
          )}
        >
          <Settings className="h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
          <span>Settings</span>
          <ChevronRight className="ml-auto h-[18px] w-[18px] 2xl:h-5 2xl:w-5" />
        </a>
      </div>
    </aside>
  );
}

function JobMainPanel({
  job,
  tab,
  analysisRef,
  recommendationsRef,
}: {
  job: Job;
  tab: string;
  analysisRef?: RefObject<HTMLElement | null>;
  recommendationsRef?: RefObject<HTMLElement | null>;
}) {
  if (tab === "Company") {
    return (
      <article className="panel p-3 2xl:p-4">
        <h3 className="text-base font-bold 2xl:text-lg">Company</h3>
        <p className="mt-3 text-[13px] leading-5 text-muted 2xl:mt-4 2xl:text-sm 2xl:leading-6">{job.companyInfo}</p>
        <div className="mt-4 grid gap-2.5 sm:grid-cols-3 2xl:mt-5 2xl:gap-3">
          <InfoStat label="Team" value={job.department} />
          <InfoStat label="Location" value={job.location} />
          <InfoStat label="Role" value={job.type} />
        </div>
      </article>
    );
  }

  if (tab === "AI Match") {
    const breakdownItems = getAiMatchBreakdownItems(job);
    const reasons = job.aiMatch?.reasons.length ? job.aiMatch.reasons : ["Run AI matching to generate role-specific reasons."];
    const gaps = job.aiMatch?.gaps.length ? job.aiMatch.gaps : ["No gaps have been calculated yet."];
    const sourceDisplay = getAiMatchSourceDisplay(job);
    const rawExplanation = buildAiMatchRawExplanation(job);
    const profileImprovements = getProfileImprovementItems(job);
    const recommendationPlan = buildRecommendationPlan(job);

    return (
      <article ref={analysisRef} tabIndex={-1} className="panel scroll-mt-4 p-3 outline-none 2xl:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-bold 2xl:text-lg">AI Match Analysis</h3>
            <p className="mt-1 text-xs font-semibold text-muted 2xl:text-sm" title={job.aiMatch?.providerError}>
              {sourceDisplay}
              {job.aiMatch?.confidence ? ` · ${job.aiMatch.confidence}` : ""}
              {" · "}
              {formatAiMatchTimestamp(job.aiMatch?.updatedAt)}
            </p>
          </div>
          <p className="text-2xl font-bold leading-none text-success 2xl:text-3xl">{formatMatchValue(job)}</p>
        </div>

        <div className="mt-4 grid gap-2 sm:grid-cols-3 2xl:mt-5 2xl:gap-3">
          <InfoStat label="Overall score" value={formatMatchValue(job)} />
          <InfoStat label="Source" value={sourceDisplay} title={job.aiMatch?.providerError} />
          <InfoStat label="Confidence" value={formatConfidence(job.aiMatch?.confidence)} />
        </div>

        <div className="mt-5 space-y-2.5 2xl:mt-6 2xl:space-y-3">
          {breakdownItems.map((item) => (
            <div key={item.key} className="grid grid-cols-[minmax(92px,0.36fr)_minmax(0,1fr)_54px] items-center gap-3">
              <span className="text-[13px] font-semibold text-muted 2xl:text-sm">{item.label}</span>
              <div className="h-2 flex-1 rounded-full bg-white/[0.08]">
                <div className="h-full rounded-full bg-success" style={{ width: `${item.progress}%` }} />
              </div>
              <span className="text-right text-[12px] font-bold text-[#d8dee8] 2xl:text-sm">
                {item.value}/{item.max}
              </span>
            </div>
          ))}
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2 2xl:mt-6">
          <div>
            <h4 className="text-[13px] font-bold 2xl:text-sm">Reasons</h4>
            <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:space-y-2 2xl:text-sm">
              {reasons.map((item) => (
                <li key={item} className="flex gap-2">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="text-[13px] font-bold 2xl:text-sm">Gaps</h4>
            <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:space-y-2 2xl:text-sm">
              {gaps.map((item) => (
                <li key={item} className="flex gap-2">
                  <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-[#ffb020]" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-5 grid gap-4 border-t border-border pt-5 md:grid-cols-2 2xl:mt-6 2xl:pt-6">
          <section>
            <h4 className="text-[13px] font-bold 2xl:text-sm">Raw Openclaw/local explanation</h4>
            <p className="mt-2.5 rounded-md border border-border bg-white/[0.025] p-3 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
              {rawExplanation}
            </p>
          </section>
          <section>
            <h4 className="text-[13px] font-bold 2xl:text-sm">Source-backed application advice</h4>
            {profileImprovements.length ? <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:space-y-2 2xl:text-sm">
              {profileImprovements.map((item) => (
                <li key={item} className="flex gap-2">
                  <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                  {item}
                </li>
              ))}
            </ul> : <p className="mt-2.5 text-[13px] leading-5 text-muted 2xl:text-sm">No source-backed profile improvements are available.</p>}
          </section>
        </div>

        <section ref={recommendationsRef} tabIndex={-1} className="mt-5 scroll-mt-4 border-t border-border pt-5 outline-none 2xl:mt-6 2xl:pt-6">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h4 className="text-[15px] font-bold 2xl:text-base">Recommendations</h4>
              <p className="mt-1 text-[12px] font-semibold text-muted 2xl:text-[13px]">Action plan for this vacancy</p>
            </div>
            <p className="text-[12px] font-bold text-success 2xl:text-[13px]">{recommendationPlan.length} actions</p>
          </div>
          <div className="mt-3 divide-y divide-border">
            {recommendationPlan.length ? recommendationPlan.map((recommendation) => (
              <div key={`${recommendation.text}-${recommendation.gain}`} className="grid gap-2 py-3 text-[13px] leading-5 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)_auto] md:items-start 2xl:text-sm">
                <div>
                  <p className="font-bold text-[#d8dee8]">{recommendation.text}</p>
                  <p className="mt-1 text-muted">{recommendation.action}</p>
                </div>
                <p className="text-muted">{recommendation.why}</p>
                <div className="md:text-right">
                  <p className="font-bold text-success">{recommendation.gain}</p>
                  <p className="mt-1 max-w-[220px] text-[12px] font-semibold text-muted md:ml-auto">{recommendation.impact}</p>
                </div>
              </div>
            )) : <p className="py-3 text-[13px] leading-5 text-muted 2xl:text-sm">No source-backed recommendations are available. Refresh AI Match after adding profile evidence.</p>}
          </div>
        </section>
      </article>
    );
  }

  if (tab === "Reviews") {
    return (
      <article className="panel p-3 2xl:p-4">
        <h3 className="text-base font-bold 2xl:text-lg">Reviews</h3>
        <div className="mt-3 space-y-2.5 2xl:mt-4 2xl:space-y-3">
          {job.reviews.map((review) => (
            <p key={review} className="rounded-md border border-border bg-white/[0.025] p-3 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
              {review}
            </p>
          ))}
        </div>
      </article>
    );
  }

  if (tab === "Similar Jobs") {
    return (
      <article className="panel p-3 2xl:p-4">
        <h3 className="text-base font-bold 2xl:text-lg">Similar Jobs</h3>
        <div className="mt-3 space-y-2.5 2xl:mt-4 2xl:space-y-3">
          {job.similarJobs.map((similarJob) => (
            <div key={similarJob} className="flex items-center justify-between rounded-md border border-border bg-white/[0.025] p-3">
              <p className="text-[13px] font-semibold text-[#d8dee8] 2xl:text-sm">{similarJob}</p>
              <ChevronDown className="h-4 w-4 -rotate-90 text-muted" />
            </div>
          ))}
        </div>
      </article>
    );
  }

  return (
    <article className="panel p-3 2xl:p-4">
      <h3 className="text-base font-bold 2xl:text-lg">Job Description</h3>
      <p className="mt-3 text-[13px] leading-5 text-muted 2xl:mt-4 2xl:text-sm 2xl:leading-6">{job.overview}</p>

      <h4 className="mt-5 text-sm font-bold 2xl:mt-7 2xl:text-base">Key Responsibilities</h4>
      <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:mt-3 2xl:space-y-2 2xl:text-sm">
        {job.responsibilities.map((item) => (
          <li key={item} className="flex gap-2">
            <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted" />
            {item}
          </li>
        ))}
      </ul>

      <h4 className="mt-5 text-sm font-bold 2xl:mt-7 2xl:text-base">Requirements</h4>
      <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:mt-3 2xl:space-y-2 2xl:text-sm">
        {job.requirements.map((item) => (
          <li key={item} className="flex gap-2">
            <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted" />
            {item}
          </li>
        ))}
      </ul>

      <div className="mt-5 flex flex-wrap gap-2 2xl:mt-7">
        {job.skills.map((skill) => (
          <span key={skill} className="tag font-semibold">
            {skill}
          </span>
        ))}
      </div>
    </article>
  );
}

function MatchPanel({
  job,
  isSavingFeedback,
  onFeedback,
  onReviewFullAnalysis,
}: {
  job: Job;
  isSavingFeedback: boolean;
  onFeedback: (job: Job, feedback: MatchFeedback) => void;
  onReviewFullAnalysis: () => void;
}) {
  const reasons = job.aiMatch?.reasons.length
    ? job.aiMatch.reasons
    : hasDisplayableMatch(job)
      ? ["Strong profile overlap", "Relevant experience", "Skills alignment"]
      : ["Run AI matching to generate role-specific reasons."];
  const gaps = job.aiMatch?.gaps ?? [];
  const sourceDisplay = getAiMatchSourceDisplay(job);
  const feedbackOptions: Array<{ feedback: MatchFeedback; label: string }> = [
    { feedback: "good_match", label: "Good match" },
    { feedback: "bad_match", label: "Bad match" },
    { feedback: "not_interested", label: "Not interested" },
  ];

  return (
    <article className="panel p-4 2xl:p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-bold 2xl:text-lg">AI Match Score</h3>
        <div className="rounded-md border border-border bg-white/[0.035] px-2 py-1 text-[10px] font-bold uppercase text-muted 2xl:text-xs" title={job.aiMatch?.providerError}>
          {sourceDisplay}
          {job.aiMatch?.confidence ? ` · ${job.aiMatch.confidence}` : ""}
        </div>
      </div>
      <p className="mt-3 text-[34px] font-bold leading-none text-success 2xl:mt-4 2xl:text-[40px]">{formatMatchValue(job)}</p>
      <div className="mt-2.5 h-2 rounded-full bg-white/[0.09] 2xl:mt-3">
        <div className="h-full rounded-full bg-success" style={{ width: `${getDisplayMatch(job)}%` }} />
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-3 2xl:mt-5">
        {feedbackOptions.map((option) => {
          const isActive = job.aiMatch?.feedback === option.feedback;
          return (
            <Button
              key={option.feedback}
              type="button"
              variant="ghost"
              disabled={isSavingFeedback}
              className={cn(
                "h-9 rounded-md border border-border bg-transparent px-2 text-[11px] font-bold text-[#d8dee8] hover:bg-white/[0.055] disabled:cursor-not-allowed disabled:opacity-55 2xl:h-10 2xl:text-xs",
                isActive && "border-accent/65 bg-accent/12 text-white",
              )}
              onClick={() => onFeedback(job, option.feedback)}
            >
              {option.label}
            </Button>
          );
        })}
      </div>
      <h4 className="mt-5 text-[13px] font-bold 2xl:mt-7 2xl:text-sm">Why this match?</h4>
      <ul className="mt-2.5 space-y-1.5 text-[13px] text-muted 2xl:mt-3 2xl:space-y-2 2xl:text-sm">
        {reasons.map((item) => (
          <li key={item} className="flex items-center gap-2">
            <Check className="h-4 w-4 text-success" />
            {item}
          </li>
        ))}
      </ul>
      {gaps.length > 0 ? (
        <>
          <h4 className="mt-5 text-[13px] font-bold 2xl:mt-7 2xl:text-sm">Gaps</h4>
          <ul className="mt-2.5 space-y-1.5 text-[13px] text-muted 2xl:mt-3 2xl:space-y-2 2xl:text-sm">
            {gaps.map((item) => (
              <li key={item} className="flex items-center gap-2">
                <CircleDot className="h-4 w-4 text-[#ffb020]" />
                {item}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <button
        type="button"
        className="mt-4 inline-flex items-center gap-2 text-[13px] font-bold text-accent transition hover:text-accent/85 2xl:mt-5 2xl:text-sm"
        onClick={onReviewFullAnalysis}
      >
        Review full analysis <span aria-hidden="true">-&gt;</span>
      </button>
    </article>
  );
}

function RecommendationsPanel({ job, onViewAllRecommendations }: { job: Job; onViewAllRecommendations: () => void }) {
  const recommendationPlan = buildRecommendationPlan(job).slice(0, 3);

  return (
    <article className="panel p-4 2xl:p-5">
      <h3 className="text-base font-bold 2xl:text-lg">Evidence-backed recommendations</h3>
      <div className="mt-3 divide-y divide-border">
        {recommendationPlan.length ? recommendationPlan.map((recommendation) => (
          <div key={recommendation.text} className="flex items-center justify-between gap-4 py-2 text-[13px] 2xl:py-2.5 2xl:text-sm">
            <div>
              <p className="text-muted">{recommendation.text}</p>
              <p className="mt-1 text-[11px] font-semibold text-[#aeb8c5]">{recommendation.action}</p>
            </div>
            <p className="shrink-0 font-bold text-success">{recommendation.gain}</p>
          </div>
        )) : <p className="py-3 text-[13px] leading-5 text-muted 2xl:text-sm">No source-backed recommendations are available.</p>}
      </div>
      <button
        type="button"
        className="mt-3 inline-flex items-center gap-2 text-[13px] font-bold text-accent transition hover:text-accent/85 2xl:text-sm"
        onClick={onViewAllRecommendations}
      >
        View all recommendations <span aria-hidden="true">-&gt;</span>
      </button>
    </article>
  );
}

function SalaryInsights({ job }: { job: Job }) {
  return (
    <article className="panel p-3 2xl:p-4">
      <h3 className="text-base font-bold 2xl:text-lg">Salary Insights</h3>
      <p className="mt-4 text-[26px] font-bold leading-none 2xl:mt-6 2xl:text-[30px]">{job.salaryAverage}</p>
      <p className="mt-1.5 text-[13px] text-muted 2xl:mt-2 2xl:text-sm">Average total compensation</p>
      <div className="mt-6 2xl:mt-8">
        <div className="relative h-2 rounded-full bg-white/[0.10]">
          <div className="absolute left-0 top-0 h-full w-1/2 rounded-full bg-accent" />
          <span className="absolute left-1/2 top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent" />
        </div>
        <div className="mt-3 flex justify-between text-[13px] font-semibold text-muted 2xl:mt-4 2xl:text-sm">
          <span>{job.salaryMin}</span>
          <span>{job.salaryAverage}</span>
          <span>{job.salaryMax}</span>
        </div>
      </div>
    </article>
  );
}

function JobDetails({ job }: { job: Job }) {
  const details = [
    ["Posted", formatJobPosted(job.posted)],
    ["Job Type", job.type],
    ["Experience", job.experience],
    ["Location", job.location],
    ["Department", job.department],
  ];

  return (
    <article className="panel p-4 2xl:p-5">
      <h3 className="text-base font-bold 2xl:text-lg">Job Details</h3>
      <dl className="mt-4 space-y-2.5 2xl:mt-5 2xl:space-y-3">
        {details.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[112px_1fr] gap-3 text-[13px] 2xl:grid-cols-[130px_1fr] 2xl:gap-4 2xl:text-sm">
            <dt className="text-muted">{label}</dt>
            <dd className="font-semibold text-[#d8dee8]">{value}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

function InfoStat({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="rounded-md border border-border bg-white/[0.025] p-2.5 2xl:p-3" title={title}>
      <p className="text-xs font-semibold uppercase text-muted">{label}</p>
      <p className="mt-1.5 text-[13px] font-bold text-white 2xl:mt-2 2xl:text-sm">{value}</p>
    </div>
  );
}

function JobMatchRing({ job }: { job: Job }) {
  const hasScore = hasDisplayableMatch(job);
  const normalizedMatch = Math.max(0, Math.min(100, job.match));
  const radius = 18.5;
  const strokeWidth = 3;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = hasScore ? circumference * (1 - normalizedMatch / 100) : circumference;

  return (
    <div className="h-10 w-10 shrink-0 text-accent 2xl:h-12 2xl:w-12" aria-label={hasScore ? `${job.match}% AI match` : "AI match not scored"} title={hasScore ? `${job.match}% match` : "AI match not scored"}>
      <svg className="block h-full w-full" viewBox="0 0 48 48" aria-hidden="true">
        <circle cx="24" cy="24" r={radius} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth={strokeWidth} />
        <circle
          cx="24"
          cy="24"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform="rotate(-90 24 24)"
        />
        <text
          x="24"
          y="24"
          fill="white"
          fontSize="13"
          fontWeight="700"
          textAnchor="middle"
          dominantBaseline="central"
          letterSpacing="0"
        >
          {hasScore ? (
            <>
              <tspan>{normalizedMatch}</tspan>
              <tspan fill="#9da6b5" fontSize="8" fontWeight="700">%</tspan>
            </>
          ) : (
            "AI"
          )}
        </text>
      </svg>
    </div>
  );
}

const jobRoleVisuals = {
  ai: { label: "AI / Machine Learning", icon: BrainCircuit, className: "border-orange-400/25 bg-orange-400/10 text-orange-300" },
  analytics: { label: "Analytics", icon: BarChart3, className: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300" },
  backend: { label: "Backend", icon: Server, className: "border-blue-400/25 bg-blue-400/10 text-blue-300" },
  data: { label: "Data Engineering", icon: Database, className: "border-cyan-400/25 bg-cyan-400/10 text-cyan-300" },
  design: { label: "Product Design", icon: Palette, className: "border-pink-400/25 bg-pink-400/10 text-pink-300" },
  devops: { label: "DevOps / Cloud", icon: Cloud, className: "border-indigo-400/25 bg-indigo-400/10 text-indigo-300" },
  frontend: { label: "Frontend", icon: Code2, className: "border-violet-400/25 bg-violet-400/10 text-violet-300" },
  mobile: { label: "Mobile", icon: Smartphone, className: "border-teal-400/25 bg-teal-400/10 text-teal-300" },
  qa: { label: "Quality Assurance", icon: FlaskConical, className: "border-amber-400/25 bg-amber-400/10 text-amber-300" },
  security: { label: "Security", icon: ShieldCheck, className: "border-red-400/25 bg-red-400/10 text-red-300" },
  software: { label: "Software Engineering", icon: Code2, className: "border-slate-400/25 bg-slate-400/10 text-slate-300" },
  general: { label: "General", icon: BriefcaseBusiness, className: "border-white/15 bg-white/[0.06] text-[#cbd2dc]" },
} as const;

type JobRoleCategory = keyof typeof jobRoleVisuals;

const jobSourceBadges: Record<Job["logo"], { label: string; text: string; className: string }> = {
  linkedin: { label: "LinkedIn", text: "in", className: "bg-[#0a66c2] text-white" },
  indeed: { label: "Indeed", text: "indeed", className: "bg-white text-[#2557a7] tracking-[-0.08em]" },
  jobs_ch: { label: "jobs.ch", text: "jobs.ch", className: "bg-white text-[#e30613] tracking-[-0.08em]" },
  manual: { label: "Manually added", text: "+", className: "bg-[#2a323d] text-[#dce2ea]" },
  figma: { label: "Figma", text: "F", className: "bg-black text-white" },
  stripe: { label: "Stripe", text: "S", className: "bg-[#635bff] text-white" },
};

function getJobSourceLabel(job: Job) {
  return jobSourceBadges[job.logo].label;
}

function getSpecializedJobRoleCategory(value: string): JobRoleCategory | null {
  const text = value.toLowerCase();
  const has = (...keywords: string[]) => keywords.some((keyword) => text.includes(keyword));

  if (has("cybersecurity", "cyber security", "information security", "security engineer", "security analyst", "infosec", "soc analyst")) return "security";
  if (has("artificial intelligence", "machine learning", "deep learning", "generative ai", "genai", "llm", "computer vision", "natural language processing", "data scientist", "data science", "pytorch", "tensorflow", "ml engineer") || /(^|[^a-z])(ai|ml)([^a-z]|$)/.test(text)) return "ai";
  if (has("data analyst", "business analyst", "analytics", "business intelligence", "tableau", "power bi", "bi developer")) return "analytics";
  if (has("data engineer", "data platform", "database engineer", "data warehouse", "etl", "snowflake", "databricks", "apache spark", "kafka")) return "data";
  if (has("devops", "site reliability", "cloud engineer", "platform engineer", "infrastructure engineer", "kubernetes", "terraform", "sre")) return "devops";
  if (has("ios", "android", "mobile developer", "mobile engineer", "react native", "flutter", "swift", "kotlin")) return "mobile";
  if (has("frontend", "front-end", "front end", "web developer", "react developer", "ui engineer", "react", "vue", "angular", "next.js")) return "frontend";
  if (has("backend", "back-end", "back end", "server-side", "api engineer", "java developer", "python developer", "golang", "node.js", "spring boot", "django", "fastapi")) return "backend";
  if (has("quality assurance", "qa engineer", "test engineer", "test automation", "software tester", "sdet", "selenium", "cypress", "playwright")) return "qa";
  if (has("product design", "product designer", "ux designer", "ui designer", "interaction designer", "design lead", "design system")) return "design";
  return null;
}

function getJobRoleCategory(job: Job): JobRoleCategory {
  const titleCategory = getSpecializedJobRoleCategory(job.title);
  if (titleCategory) return titleCategory;

  const normalizedTitle = job.title.toLowerCase();
  if (normalizedTitle.includes("full stack") || normalizedTitle.includes("full-stack")) return "software";

  const departmentCategory = getSpecializedJobRoleCategory(job.department);
  if (departmentCategory) return departmentCategory;

  const skillsCategory = getSpecializedJobRoleCategory(job.skills.join(" "));
  if (skillsCategory) return skillsCategory;

  if (["software engineer", "software developer", "application developer", "engineer", "developer"].some((keyword) => normalizedTitle.includes(keyword))) return "software";
  return "general";
}

function JobRoleIcon({ job, large = false, compact = false }: { job: Job; large?: boolean; compact?: boolean }) {
  const role = jobRoleVisuals[getJobRoleCategory(job)];
  const source = jobSourceBadges[job.logo];
  const Icon = role.icon;
  const sizeClass = compact ? "h-9 w-9 2xl:h-11 2xl:w-11" : large ? "h-16 w-16 2xl:h-[88px] 2xl:w-[88px]" : "h-11 w-11 2xl:h-14 2xl:w-14";
  const iconSizeClass = compact ? "h-4 w-4 2xl:h-5 2xl:w-5" : large ? "h-8 w-8 2xl:h-11 2xl:w-11" : "h-5 w-5 2xl:h-6 2xl:w-6";
  const badgeSizeClass = compact
    ? "-bottom-0.5 -right-0.5 h-3.5 min-w-3.5 px-0.5 text-[6px] 2xl:h-4 2xl:min-w-4 2xl:text-[7px]"
    : large
      ? "-bottom-1 -right-1 h-6 min-w-6 px-1 text-[9px] 2xl:h-7 2xl:min-w-7 2xl:text-[10px]"
      : "-bottom-0.5 -right-0.5 h-4 min-w-4 px-0.5 text-[7px] 2xl:h-5 2xl:min-w-5 2xl:text-[8px]";

  return (
    <div
      role="img"
      aria-label={`${role.label} role · ${source.label}`}
      title={`${role.label} · ${source.label}`}
      className={cn("relative grid shrink-0 place-items-center rounded-lg border", role.className, sizeClass)}
    >
      <Icon className={iconSizeClass} strokeWidth={large ? 1.7 : 1.9} aria-hidden="true" />
      <span
        aria-hidden="true"
        className={cn("absolute grid place-items-center rounded border border-[#111820] font-black leading-none shadow-sm", source.className, badgeSizeClass)}
      >
        {source.text}
      </span>
    </div>
  );
}
