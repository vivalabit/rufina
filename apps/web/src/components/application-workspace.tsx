"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Download,
  ExternalLink,
  FileCheck2,
  FileText,
  Info,
  LoaderCircle,
  Mail,
  MessageSquareText,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AiBackend } from "@/lib/ai-source";
import {
  getAiMatchAnalysisStatus,
  hasCurrentApplicationGuide,
  isLegacyAiMatch,
} from "@/lib/ai-match";
import {
  RetryablePackError,
  retryPackOperation,
} from "@/lib/application-pack";
import {
  importLegacyCandidateConfirmations,
  isCandidateConfirmationComplete,
  isMeaningfulCandidateConfirmation,
  type CandidateConfirmation,
  type CandidateConfirmationResponse,
} from "@/lib/candidate-confirmations";
import { isGeneratedDocumentOutdated } from "@/lib/generation-provenance";
import { normalizeJobsChJobUrl } from "@/lib/job-url";
import {
  canReuseResumeRenderSource,
  resumeArtifactGenerationMode,
  resumeRenderSource,
  resumeRenderUrl,
  type ResumeGenerationMode,
  type ResumeRenderSource,
} from "@/lib/resume-generation";
import {
  getDocumentVersionDownloadWarnings,
  getGeneratedDocumentReadiness,
} from "@/lib/document-readiness";
import {
  AI_GENERATION_REQUEST_TIMEOUT_MS,
  API_HEALTH_TIMEOUT_MS,
  apiUnavailableMessage,
  fetchWithTimeout,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";
import {
  completedResumeTailoringProgress,
  ResumeTailoringProgressPanel,
  type ResumeTailoringProgress,
} from "@/components/resume-tailoring-progress";
import {
  ResumePdfReview,
  ResumeTemplatePicker,
  type ResumePdfArtifact,
} from "@/components/resume-pdf-review";
import { DocumentPdfPreview } from "@/components/document-pdf-preview";
import type {
  ResumeTemplate,
  ResumeTemplateId,
} from "@/lib/resume-templates";

type WorkspaceJob = {
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
    applicationGuide?: ApplicationGuide;
  };
};

type ApplicationGuide = {
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
  status: string;
  nextStep: string;
  notes: string;
  job: WorkspaceJob;
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

type GeneratedDocumentVersion = {
  id: string;
  version: number;
  content: string;
  createdAt: string;
  hasRenderedDocx?: boolean;
  hasRenderedArtifact?: boolean;
  artifact?: {
    fileName: ResumePdfArtifact["fileName"];
    contentType: ResumePdfArtifact["contentType"];
    templateId?: ResumePdfArtifact["templateId"];
    templateVersion?: ResumePdfArtifact["templateVersion"];
    sourceAtsFinalReviewId?: ResumePdfArtifact["sourceAtsFinalReviewId"];
    sourceImaginatorResumeId?: ResumePdfArtifact["sourceImaginatorResumeId"];
    finalResumeJson?: ResumePdfArtifact["finalResumeJson"];
    stageResults?: ResumePdfArtifact["stageResults"];
    provenance?: ResumePdfArtifact["provenance"];
  } | null;
  factualValidation: {
    status?: string;
    checkedChanges?: number;
  };
  visualValidation: {
    status?: string;
    sourcePageCount?: number;
    renderedPageCount?: number;
    pageCountChanged?: boolean;
    linksPreserved?: boolean;
    sourceLinkCount?: number;
    renderedLinkCount?: number;
    missingLinkCount?: number;
    addedLinkCount?: number;
    sourcePdfLinkCount?: number;
    renderedPdfLinkCount?: number;
    missingPdfLinkCount?: number;
    addedPdfLinkCount?: number;
    linkLocationChangedCount?: number;
    sourceTextBoxCount?: number;
    renderedTextBoxCount?: number;
    missingTextCount?: number;
    missingTextSamples?: string[];
    disappearedSourceTextCount?: number;
    disappearedSourceTextSamples?: string[];
    textGeometryChangedCount?: number;
    textOutsidePageCount?: number;
    sourceImageCount?: number;
    renderedImageCount?: number;
    sourceImageBoxCount?: number;
    renderedImageBoxCount?: number;
    missingSourceImageCount?: number;
    missingPdfImageCount?: number;
    imageGeometryChangedCount?: number;
    imageOutsidePageCount?: number;
    tableOverflow?: boolean;
    cellOverflowCount?: number;
    tableStructureIssueCount?: number;
    issues?: string[];
  };
  diff: Array<{
    blockId: string;
    spanId?: string;
    type: string;
    original: string;
    replacement: string;
    reason: string;
  }>;
};

type GeneratedDocument = {
  id: string;
  type: "cover_letter" | "tailored_resume";
  title: string;
  jobId: string | null;
  applicationIds: string[];
  currentVersion: number;
  createdAt: string;
  updatedAt: string;
  generationFingerprint: string | null;
  currentGenerationFingerprint: string | null;
  generationModel: string | null;
  generationBackend?: string | null;
  inputVersions: Record<string, unknown>;
  versions: GeneratedDocumentVersion[];
  versionsTotal?: number;
  versionsHasMore?: boolean;
};

type AiConfiguration = {
  providerName: string;
  backend: AiBackend;
};

type PackStageId = "resume_generation" | "resume_validation" | "cover_letter_generation" | "saving";
type PackProgressStatus = "active" | "retrying" | "failed" | "completed" | "partial";
type WorkspaceStep = "review" | "confirm" | "create" | "final";
type CoverLetterDraft = {
  documentId?: string;
  title: string;
  generationArtifactId: string;
  validationArtifactId?: string;
};

type CoverLetterDraftResult = {
  draft: CoverLetterDraft;
  generatedContent: string;
};

type DocumentGenerationCorrection = {
  feedback: string;
  previousDraft: string;
};

type CurrentMasterResume = {
  masterResumeId: string;
  version: number;
  createdAt: string;
  updatedAt: string;
};

type PackProgress = {
  jobId: string;
  stage: PackStageId;
  status: PackProgressStatus;
  attempt: number;
  message: string;
};

type DocumentTemplate = {
  id: string;
  type: "cover_letter" | "tailored_resume";
  name: string;
  fileName: string;
  builtIn: boolean;
  createdAt: string;
  updatedAt: string;
};

type DocumentChatTarget = GeneratedDocument["type"] | "question";

type DocumentChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
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

const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const docxContentType = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const defaultAiConfiguration: AiConfiguration = {
  providerName: "OpenAI via OpenClaw/Codex",
  backend: "openclaw_codex",
};
const confirmationAnswerMaxChars = 1_500;
const documentRevisionMessageMaxChars = 7_000;
const documentGenerationMessageMaxChars = 11_500;
const resumeTemplateStorageKeyPrefix = "tasko.resume-template.v1";
const resumeGenerationModeStorageKeyPrefix = "tasko.resume-generation-mode.v1";
const resumeGenerationModes: ReadonlyArray<{
  id: ResumeGenerationMode;
  name: string;
  description: string;
  stages: string;
}> = [
  {
    id: "recruiter_xyz_ats",
    name: "Recruiter → XYZ → ATS",
    description:
      "Deep evidence-backed tailoring with recruiter analysis, XYZ experience rewriting, and a final ATS review.",
    stages: "3 AI stages",
  },
  {
    id: "imaginator",
    name: "Imaginator",
    description:
      "Creates an idealized candidate and may invent experience, skills, achievements, and qualifications. Employer names, education, and identity stay locked.",
    stages: "Creative generation + protected-fact audit",
  },
];
const defaultResumeGenerationMode = resumeGenerationModes[0].id;
const coverLetterRecipientQuestion = {
  id: "cover-letter-recipient-name",
  requirement: "Named recruiter or intended hiring contact",
  question: "Is a recruiter or intended hiring contact named for this application?",
  why: "A verified recipient name allows the letter to use a direct greeting; otherwise it will address the hiring team.",
  claimIfConfirmed: "The named person is the recruiter or intended hiring contact for this application.",
  blocking: false,
} satisfies NonNullable<ApplicationGuide["clarificationQuestions"]>[number];
const coverLetterCompanyContactQuestion = {
  id: "cover-letter-company-contact",
  requirement: "Known employee at the hiring company",
  question: "Do you know or have you spoken with an employee at this company?",
  why: "A genuine company contact can give the cover letter a more personal opening.",
  claimIfConfirmed: "The candidate knows or has spoken with the named employee, and that contact strengthened the candidate's positive impression of the company.",
  blocking: false,
} satisfies NonNullable<ApplicationGuide["clarificationQuestions"]>[number];
const coverLetterContextQuestions = [
  coverLetterRecipientQuestion,
  coverLetterCompanyContactQuestion,
];
const coverLetterContextQuestionIds = new Set<string>(
  coverLetterContextQuestions.map((question) => question.id),
);
const packStageDefinitions: Array<{ id: PackStageId; label: string }> = [
  { id: "resume_generation", label: "Generate CV" },
  { id: "resume_validation", label: "Validate CV" },
  { id: "cover_letter_generation", label: "Generate cover letter" },
  { id: "saving", label: "Save pack" },
];

function createId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function isResumeGenerationMode(value: string | null): value is ResumeGenerationMode {
  return resumeGenerationModes.some((mode) => mode.id === value);
}

function documentFileName(document: GeneratedDocument, version = document.currentVersion) {
  const artifact = document.versions.find((item) => item.version === version)?.artifact;
  if (artifact?.fileName) return artifact.fileName;
  const base = document.title.trim().normalize("NFC").replace(/[^\p{L}\p{M}\p{N}._-]+/gu, "-").replace(/^[._-]+|[._-]+$/g, "") || "rufina-document";
  return `${base}-v${version}.docx`;
}

function documentArtifactLabel(document: GeneratedDocument, version = document.currentVersion) {
  const contentType = document.versions.find((item) => item.version === version)?.artifact?.contentType;
  return contentType === "application/pdf" ? "PDF" : "DOCX";
}

function resumeDocxDownload(document: GeneratedDocument) {
  const version = document.versions.find(
    (item) => item.version === document.currentVersion,
  );
  const artifact = version?.artifact;
  const source = resumeRenderSource(artifact);
  if (
    artifact?.contentType !== "application/pdf"
    || !source
  ) {
    return null;
  }
  const templateId = artifact.templateId ?? "classic_single";
  const fileName = artifact.fileName.toLowerCase().endsWith(".pdf")
    ? `${artifact.fileName.slice(0, -4)}.docx`
    : "resume.docx";
  return {
    href: resumeRenderUrl(apiBaseUrl, source, "docx", templateId),
    fileName,
  };
}

function coverLetterPdfDownload(
  document: GeneratedDocument,
  version = document.currentVersion,
) {
  const artifact = document.versions.find(
    (item) => item.version === version,
  )?.artifact;
  if (artifact?.contentType === "application/pdf") return null;
  const sourceFileName = documentFileName(document, version);
  const fileName = sourceFileName.toLowerCase().endsWith(".docx")
    ? `${sourceFileName.slice(0, -5)}.pdf`
    : `${sourceFileName}.pdf`;
  const versionQuery = version === document.currentVersion
    ? ""
    : `?version=${version}`;
  return {
    href: `${apiBaseUrl}/documents/${encodeURIComponent(document.id)}/pdf${versionQuery}`,
    fileName,
  };
}

function confirmDocumentDownload(
  event: React.MouseEvent<HTMLAnchorElement>,
  warnings: string[],
) {
  if (warnings.length === 0) return;
  const confirmed = window.confirm(
    `Warning: ${warnings.join("; ")}. This file may not be ready to submit. Download anyway?`,
  );
  if (!confirmed) event.preventDefault();
}

function formatVersionTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function CollapsibleDocumentPreview({
  title,
  description,
  available,
  children,
}: {
  title: string;
  description: string;
  available: boolean;
  children: React.ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <details
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      className="group border-t border-border"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-xs font-bold text-[#1d1e1c]">
        <span>
          <span className="block text-sm text-foreground">{title}</span>
          <span className="mt-1 block text-[10px] font-normal leading-4 text-muted">
            {available ? description : "Available after document generation"}
          </span>
        </span>
        <ChevronRight className="h-4 w-4 shrink-0 text-muted transition group-open:rotate-90" />
      </summary>
      {isOpen ? (
        <div className="border-t border-border py-5">
          {available ? children : (
            <div className="grid min-h-32 place-items-center border border-dashed border-border bg-black/15 px-4 text-center">
              <p className="text-[10px] font-bold text-muted">
                Generate the document to open its exact PDF preview.
              </p>
            </div>
          )}
        </div>
      ) : null}
    </details>
  );
}

function CoverLetterTemplateCard({
  apiBaseUrl,
  template,
}: {
  apiBaseUrl: string;
  template: DocumentTemplate | null;
}) {
  const thumbnailUrl = template
    ? `${apiBaseUrl}/documents/templates/${encodeURIComponent(template.id)}/thumbnail?version=${encodeURIComponent(template.updatedAt)}&format=9x16`
    : "";
  const [loadedThumbnailUrl, setLoadedThumbnailUrl] = useState("");
  const [failedThumbnailUrl, setFailedThumbnailUrl] = useState("");
  const thumbnailReady = Boolean(
    thumbnailUrl && loadedThumbnailUrl === thumbnailUrl,
  );
  const thumbnailFailed = Boolean(
    thumbnailUrl && failedThumbnailUrl === thumbnailUrl,
  );

  return (
    <div className="mt-4 border-t border-border pt-4">
      <div className="grid grid-cols-[76px_minmax(0,1fr)] items-center gap-4">
        <div
          aria-label={`${template?.name ?? "Standard cover letter"} selected template`}
          className="min-w-0"
        >
          <span className="relative mx-auto block w-full max-w-[9rem]">
            <span
              data-testid="cover-letter-template-thumbnail"
              className="relative block aspect-[9/16] w-full overflow-hidden border border-slate-300/70 bg-white shadow-[0_8px_24px_rgba(0,0,0,0.3)]"
            >
              {thumbnailUrl && !thumbnailFailed ? (
                <img
                  src={thumbnailUrl}
                  alt={`${template?.name ?? "Standard cover letter"} template preview`}
                  loading="lazy"
                  decoding="async"
                  onLoad={() => setLoadedThumbnailUrl(thumbnailUrl)}
                  onError={() => setFailedThumbnailUrl(thumbnailUrl)}
                  className={cn(
                    "h-full w-full object-cover transition-opacity duration-200",
                    thumbnailReady ? "opacity-100" : "opacity-0",
                  )}
                />
              ) : thumbnailFailed ? (
                <span className="flex h-full flex-col items-center justify-center gap-1 text-slate-500">
                  <FileText className="h-5 w-5" />
                  <span className="text-[6px] font-bold uppercase tracking-[0.08em]">
                    Preview unavailable
                  </span>
                </span>
              ) : null}
              {!thumbnailReady && !thumbnailFailed ? (
                <span
                  aria-hidden="true"
                  className="absolute inset-0 flex items-center justify-center"
                >
                  <LoaderCircle className="h-5 w-5 animate-spin text-slate-500" />
                </span>
              ) : null}
            </span>
          </span>
        </div>
        <div className="min-w-0">
          <p className="text-[9px] font-black uppercase tracking-[0.12em] text-muted">
            Cover letter template
          </p>
          <p className="mt-2 text-[11px] font-bold text-foreground">
            {template?.name ?? "Standard cover letter"}
          </p>
          <p className="mt-1 text-[9px] leading-4 text-muted">
            Built-in · fixed Swiss-style structure
          </p>
        </div>
      </div>
      <p className="mt-3 text-[9px] leading-4 text-muted">
        Company details are researched automatically · no DOCX upload required
      </p>
    </div>
  );
}

function inferSourceLanguage(fileName: string, title = "") {
  const value = `${fileName} ${title}`.toLowerCase();
  if (/(?:^|[\s_.-])(de|deu|ger)(?:[\s_.-]|$)|deutsch|german/.test(value)) return "German";
  if (/(?:^|[\s_.-])(en|eng)(?:[\s_.-]|$)|english/.test(value)) return "English";
  return "";
}

function detectLegacyJobLanguage(job: WorkspaceJob) {
  const text = [job.title, job.overview, ...job.requirements, ...job.responsibilities].join(" ").toLowerCase();
  const germanMarkers = [" der ", " die ", " das ", " und ", " mit ", " für ", " wir ", " sie ", "aufgaben", "anforderungen", "kenntnisse", "bewerbung"];
  const englishMarkers = [" the ", " and ", " with ", " for ", " we ", " you ", "responsibilities", "requirements", "skills", "application"];
  const padded = ` ${text} `;
  const germanScore = germanMarkers.reduce((score, marker) => score + padded.split(marker).length - 1, 0);
  const englishScore = englishMarkers.reduce((score, marker) => score + padded.split(marker).length - 1, 0);
  return germanScore > englishScore ? "German" : "English";
}

function reviewSection(title: string, values: string[]) {
  return values.length ? `${title}\n${values.map((value) => `• ${value}`).join("\n")}` : "";
}

function buildSavedApplicationReview(job: WorkspaceJob) {
  if (!hasCurrentApplicationGuide(job.aiMatch)) return "";
  const guide = job.aiMatch?.applicationGuide;
  if (!guide) return "";
  const language = guide?.language || detectLegacyJobLanguage(job);
  const reasons = job.aiMatch?.reasons ?? [];
  const gaps = job.aiMatch?.gaps ?? [];
  const sections = [
    `VACANCY LANGUAGE: ${language}`,
    reviewSection("ROLE MISSION", guide.roleMission ? [guide.roleMission] : []),
    reviewSection("BEST POSITIONING", [guide?.positioning || reasons[0] || `Emphasize verified experience that is directly relevant to ${job.title}.`]),
    reviewSection("HIRING PRIORITIES", guide.hiringPriorities ?? []),
    reviewSection("MUST HAVE", guide.mustHave ?? []),
    reviewSection("NICE TO HAVE", guide.niceToHave ?? []),
    reviewSection("HARD CONSTRAINTS", guide.hardConstraints ?? []),
    reviewSection("CV IMPROVEMENTS", guide?.cvImprovements?.length ? guide.cvImprovements : gaps.length ? gaps : reasons),
    reviewSection("COVER LETTER STRATEGY", guide?.coverLetterStrategy?.length ? guide.coverLetterStrategy : reasons),
    reviewSection("GAPS AND RISKS", guide?.risks?.length ? guide.risks : gaps),
    reviewSection("KEYWORDS AND EVIDENCE TO EMPHASIZE", guide?.keywords?.length ? guide.keywords : job.skills.slice(0, 8)),
    reviewSection("LIKELY APPLICATION QUESTIONS", guide?.applicationQuestions ?? []),
    reviewSection("FINAL BEFORE-SUBMITTING CHECKLIST", guide?.finalChecklist?.length ? guide.finalChecklist : ["Verify every claim against the source CV.", "Confirm the selected documents and language before submitting."]),
  ];
  return sections.filter(Boolean).join("\n\n");
}

export function buildDocumentGenerationPrompt(
  targetLanguage: string,
) {
  const headerInstructions = "Fill every editable field in the bundled cover-letter template instead of leaving placeholder text unchanged. Use confirmation:company-header-research for the official recipientCompany and verified address, confirmation:cover-letter-recipient-name for recipientName when present, the candidate profile location plus generation date for letterDate, the exact vacancy title for the subject, and profile:name for candidateName. Keep the recipient block in exactly four lines: official company name; recruiter or Hiring Team; street and building number; postal code, city, and country. Split the researched full address between recipientStreet and recipientCity at the boundary after the street and building number. Do not invent, shorten, or omit any part of the researched company address.";
  return `${headerInstructions} Act as an experienced career consultant and recruiter who writes personalized cover letters for strong candidates. Using the complete candidate resume/profile and vacancy in CONTEXT_JSON, write a compelling cover letter tailored specifically to this role in ${targetLanguage}. Before writing, silently analyze the vacancy: identify its key responsibilities, must-have and preferred requirements, most important competencies, the employer problems the new hire should solve, and the company's own professional vocabulary. Silently analyze the resume: identify the most relevant experience, projects, responsibilities, recurring areas of work, and transferable skills that prove fit, as well as the candidate's strongest competitive advantages. Build the letter around the mapping “employer need → verified candidate capability → benefit the candidate can deliver”. Use confirmation:cover-letter-additional-context when present for motivation, proud achievements, reasons for changing roles, details to emphasize, and details to avoid. Never invent facts, achievements, numbers, tools, experience, feelings, names, praise, or endorsement. When evidence is insufficient, use a neutral formulation instead of asking questions during document generation. Write approximately 250–350 words when the editable template capacity allows it. Use a confident, professional, natural tone and language clear to a non-technical recruiter. Personalize the letter to the company and role. The first two or three sentences should immediately show why the candidate is relevant. The second substantive body paragraph must give a concise, recruiter-friendly synthesis of what the candidate has done across their experience: the kinds of systems, products, workflows, or business problems they worked on; their recurring responsibilities; and the broader operational value of that work. Generalize only from verified resume evidence. Describe two to four coherent capability areas rather than walking through employers or roles. Do not copy, closely paraphrase, enumerate, or compress achievement bullets from the resume in this paragraph. Do not include metrics, percentages, counts, revenue, time savings, or other numbers in this paragraph. It should read as a natural professional overview, similar in abstraction and flow to: “Throughout my experience, I have built [types of systems] for [types of real-world use cases]. I have focused on [recurring responsibilities and operational outcomes]. I also have experience with [another verified capability area].” Use the pattern, not these facts or exact wording. In the following paragraph, connect the most relevant capabilities to the employer's needs and explain how the candidate can help solve the company's tasks. Include at most one concise, verified example elsewhere in the letter when it materially improves credibility; do not turn that paragraph into a list of CV metrics or retell the whole CV. Explain the specific attraction of the role and company using only available evidence, and focus equally on the benefit to the employer. If the candidate is changing profession or industry, explain transferable value without defensiveness. Do not emphasize unmet requirements. Avoid bureaucracy, overly complex sentences, generic AI phrasing, flattery, overconfidence, and unsupported clichés such as “ideal candidate”, “team player”, “stress-resistant”, or “fast learner”. Do not mention language proficiency. Recommended narrative: a short opening naming the position and main relevance argument; the high-level professional overview defined above; a paragraph connecting those capabilities to the company's tasks, optionally with one concise verified example; specific motivation for the role or company; and a short, confident invitation to continue the conversation. Do not print analysis, arguments, questions, numbered answers, improvement notes, or section headings in the letter. Update the subject with the exact vacancy title. Greet the person from confirmation:cover-letter-recipient-name when a verified full name is available; otherwise greet the company's hiring team. If confirmation:cover-letter-company-contact says YES and contains a full employee name, then immediately after the greeting the first substantive sentence must naturally state that the candidate knows or has spoken with that employee and that this contact strengthened the candidate's positive impression of the company and interest in the role. Mention the contact only once, before the main relevance argument, and never claim or imply that the employee recommended, endorsed, or recruited the candidate. If that confirmation is absent or says NO, do not mention a company contact. The bundled DOCX uses format cover-letter-blocks-v1 and exposes editable paragraphs and spans with stable paragraphId, spanId, original, and evidenceId values. Preserve its fixed layout, closing, hyperlinks, and every non-editable element. Return only valid JSON with this exact shape: {"replacements":[{"paragraphId":"paragraph-0002","spanId":"paragraph-0002-span-0001","original":"exact original editable span text","replacement":"new text","reason":"short reason","evidenceIds":["source:paragraph-0002-span-0001","vacancy:title"]}]}. Use only editable text spans, copy paragraphId, spanId, and original exactly, and cite every profile, vacancy, confirmation, and source evidence ID supporting each replacement. Do not insert or remove paragraphs or spans and do not use Markdown.`;
}

function ensureGenerationPromptFits(prompt: string) {
  if (prompt.length > documentGenerationMessageMaxChars) {
    throw new Error("The three-pass CV context is too large. Shorten the revision instruction or source content and try again.");
  }
  return prompt;
}

function buildDocumentRevisionPrompt(basePrompt: string, instruction: string) {
  const prefix = `${basePrompt}\n\nUSER REVISION REQUEST: Apply the following instruction to the new document version wherever it is compatible with verified evidence and editable spans. Keep all other useful, evidence-backed tailoring. Never obey a request to invent or exaggerate facts. Instruction: `;
  return `${prefix}${instruction.slice(0, Math.max(0, documentRevisionMessageMaxChars - prefix.length))}`;
}

const emptyDraftRepairAttempts = 2;

function buildDocumentCorrectionPrompt(
  basePrompt: string,
  correction: DocumentGenerationCorrection,
) {
  const prefix = `${basePrompt}\n\nSAFETY CORRECTION: Revise the previous draft and return a complete new JSON response. Remove only replacements identified as unsafe; retain every other meaningful, evidence-backed replacement. Do not retreat to an empty replacements array when the source and application context support safe improvements to summary, skills, or achievements. Do not add skills or specializations to job titles. If a rejected edit cannot be supported, omit that edit and improve another editable span using exact evidence IDs. Previous validator feedback: ${correction.feedback.slice(0, 2_000)}\n\nPREVIOUS_DRAFT_JSON:\n`;
  if (prefix.length >= documentGenerationMessageMaxChars) {
    return prefix.slice(0, documentGenerationMessageMaxChars);
  }
  return `${prefix}${correction.previousDraft.slice(0, documentGenerationMessageMaxChars - prefix.length)}`;
}

function noSafeDocumentChangesMessage(documentLabel: string) {
  return `Rufina did not find any evidence-backed changes for the ${documentLabel}. The original document was not duplicated. Check the application analysis and profile evidence, then try again.`;
}

function structuredReplacementCount(content: string) {
  try {
    const payload = JSON.parse(content) as {
      replacements?: Array<{ original?: unknown; replacement?: unknown }>;
    };
    if (!Array.isArray(payload.replacements)) return null;
    return payload.replacements.filter((replacement) => (
      typeof replacement?.original === "string"
      && typeof replacement.replacement === "string"
      && replacement.replacement.trim() !== replacement.original.trim()
    )).length;
  } catch {
    return null;
  }
}

async function readApiError(response: Response, fallback: string) {
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  if (typeof payload?.detail === "string" && payload.detail.trim()) return payload.detail;
  if (
    payload?.detail
    && typeof payload.detail === "object"
    && "message" in payload.detail
    && typeof payload.detail.message === "string"
    && payload.detail.message.trim()
  ) return payload.detail.message;
  return fallback;
}

function reusableResumeSource(
  document: GeneratedDocument | undefined,
  isOutdated: boolean,
  selectedMode: ResumeGenerationMode,
): ResumeRenderSource | null {
  const version = document?.versions.find(
    (candidate) => candidate.version === document.currentVersion,
  );
  const artifact = version?.artifact;
  if (artifact?.contentType !== "application/pdf") return null;
  return canReuseResumeRenderSource(artifact, {
    isOutdated,
    selectedMode,
  });
}

function generatedDocumentLanguage(
  document: GeneratedDocument | undefined,
): "English" | "German" | null {
  const inputLanguage = document?.inputVersions.documentLanguage;
  if (inputLanguage === "English" || inputLanguage === "German") {
    return inputLanguage;
  }
  const version = document?.versions.find(
    (candidate) => candidate.version === document.currentVersion,
  );
  const resumeLanguage = version?.artifact?.finalResumeJson?.language;
  return resumeLanguage === "English" || resumeLanguage === "German"
    ? resumeLanguage
    : null;
}

function evidenceStatusMeta(status: NonNullable<ApplicationGuide["evidenceMatrix"]>[number]["status"]) {
  if (status === "verified") return { label: "Verified", className: "border-success/35 bg-success/10 text-success" };
  if (status === "transferable") return { label: "Transferable", className: "border-[#fa5d00]/35 bg-[#fa5d00]/10 text-accent" };
  if (status === "missing") return { label: "Missing", className: "border-accent/25 bg-accent/10 text-accent" };
  return { label: "Confirm", className: "border-accent/25 bg-accent/10 text-accent" };
}

function buildGroundedAdvice(prompt: string, guide?: ApplicationGuide) {
  const groundedEvidence = (guide?.evidenceMatrix ?? []).filter(
    (item) => ["verified", "transferable"].includes(item.status) && item.sources?.length,
  );
  if (!groundedEvidence.length) {
    return "No source-backed advice is available. Refresh AI Match after adding evidence to your profile.";
  }
  const heading = prompt === "What are the biggest risks?"
    ? "Only source-backed strengths are shown; unresolved risks require confirmation."
    : prompt === "Help with application questions"
      ? "Use these source-backed facts in application answers:"
      : "Emphasize these source-backed facts:";
  return [
    heading,
    ...groundedEvidence.map((item) => {
      const sources = item.sources
        ?.map((source) => `${source.label}: “${source.excerpt}”`)
        .join("; ");
      return `• ${item.requirement}: ${item.evidence}\n  Action: ${item.action}\n  Sources: ${sources}`;
    }),
  ].join("\n");
}

export function ApplicationWorkspace({
  application,
  profile,
  backLabel = "Applications",
  onBack,
  onOpenAssistant,
  onDocumentAttached,
  onMarkApplied,
  onRefreshAnalysis,
  isAnalysisRefreshing,
}: ApplicationWorkspaceProps) {
  const [documents, setDocuments] = useState<GeneratedDocument[]>([]);
  const [documentsLoaded, setDocumentsLoaded] = useState(false);
  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [resumeTemplates, setResumeTemplates] = useState<ResumeTemplate[]>([]);
  const [selectedResumeTemplateId, setSelectedResumeTemplateId] = useState<ResumeTemplateId>("classic_single");
  const [resumeTemplateNotice, setResumeTemplateNotice] = useState("");
  const [selectedResumeGenerationMode, setSelectedResumeGenerationMode] =
    useState<ResumeGenerationMode>(defaultResumeGenerationMode);
  const [currentMasterResume, setCurrentMasterResume] =
    useState<CurrentMasterResume | null>(null);
  const [masterResumeLoaded, setMasterResumeLoaded] = useState(false);
  const [languageMode, setLanguageMode] = useState<"auto" | "English" | "German">("auto");
  const [generationType, setGenerationType] = useState<GeneratedDocument["type"] | "">("");
  const [isGeneratingPack, setIsGeneratingPack] = useState(false);
  const [packProgress, setPackProgress] = useState<PackProgress | null>(null);
  const [resumeTailoringProgress, setResumeTailoringProgress] =
    useState<ResumeTailoringProgress | null>(null);
  const [restoringVersionKey, setRestoringVersionKey] = useState("");
  const [loadingVersionHistoryId, setLoadingVersionHistoryId] = useState("");
  const [deletingDocumentId, setDeletingDocumentId] = useState("");
  const [documentError, setDocumentError] = useState("");
  const [candidateConfirmations, setCandidateConfirmations] = useState<Record<string, CandidateConfirmation>>({});
  const [confirmationsDirty, setConfirmationsDirty] = useState(false);
  const [confirmationSyncStatus, setConfirmationSyncStatus] = useState<"loading" | "saving" | "saved" | "unsaved" | "error">("loading");
  const [confirmationSyncMessage, setConfirmationSyncMessage] = useState("");
  const [advice, setAdvice] = useState("");
  const [advicePrompt, setAdvicePrompt] = useState("");
  const [isLoadingAdvice, setIsLoadingAdvice] = useState(false);
  const [documentChatTarget, setDocumentChatTarget] =
    useState<DocumentChatTarget>("question");
  const [documentChatInput, setDocumentChatInput] = useState("");
  const [documentChatMessages, setDocumentChatMessages] = useState<DocumentChatMessage[]>([]);
  const [isDocumentChatResponding, setIsDocumentChatResponding] = useState(false);
  const [analysisTab, setAnalysisTab] = useState<"overview" | "evidence" | "strategy">("overview");
  const [activeWorkspaceStep, setActiveWorkspaceStep] = useState<WorkspaceStep>(
    () => hasCurrentApplicationGuide(application?.job.aiMatch) ? "create" : "review",
  );
  const [aiConfiguration, setAiConfiguration] = useState<AiConfiguration>(defaultAiConfiguration);
  const [apiHealth, setApiHealth] = useState<"checking" | "available" | "unavailable">("checking");
  const [apiRetryVersion, setApiRetryVersion] = useState(0);

  function selectResumeTemplate(templateId: ResumeTemplateId) {
    setSelectedResumeTemplateId(templateId);
    setResumeTemplateNotice("");
    if (application) {
      window.localStorage.setItem(
        `${resumeTemplateStorageKeyPrefix}.${application.id}`,
        templateId,
      );
    }
  }

  function selectResumeGenerationMode(mode: ResumeGenerationMode) {
    setSelectedResumeGenerationMode(mode);
    if (application) {
      window.localStorage.setItem(
        `${resumeGenerationModeStorageKeyPrefix}.${application.id}`,
        mode,
      );
    }
  }

  function handleResumeTemplateUnavailable(templateId: ResumeTemplateId) {
    const remainingTemplates = resumeTemplates.filter(
      (template) => template.id !== templateId,
    );
    const fallbackTemplate =
      remainingTemplates.find(
        (template) => template.id === "classic_single",
      ) ??
      remainingTemplates.find((template) => template.kind === "bundled") ??
      remainingTemplates[0];
    setResumeTemplates(remainingTemplates);
    setSelectedResumeTemplateId(fallbackTemplate?.id ?? "");
    setResumeTemplateNotice(
      "The selected resume template was deleted or is no longer available. Choose another template and render again.",
    );
    if (!application) return;
    const storageKey = `${resumeTemplateStorageKeyPrefix}.${application.id}`;
    if (fallbackTemplate) {
      window.localStorage.setItem(storageKey, fallbackTemplate.id);
    } else {
      window.localStorage.removeItem(storageKey);
    }
  }

  function retryApiRequests() {
    setApiHealth("checking");
    setDocumentError("");
    setConfirmationSyncMessage("");
    setApiRetryVersion((current) => current + 1);
  }

  useEffect(() => {
    const controller = new AbortController();
    setApiHealth("checking");
    fetchWithTimeout(
      `${apiBaseUrl}/health`,
      { cache: "no-store", signal: controller.signal },
      API_HEALTH_TIMEOUT_MS,
    )
      .then((response) => {
        if (!response.ok) throw new Error("API health check failed");
        setApiHealth("available");
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setApiHealth("unavailable");
      });
    return () => controller.abort();
  }, [apiRetryVersion]);

  useEffect(() => {
    if (!application) return;
    const savedTemplateId = window.localStorage.getItem(
      `${resumeTemplateStorageKeyPrefix}.${application.id}`,
    );
    const savedGenerationMode = window.localStorage.getItem(
      `${resumeGenerationModeStorageKeyPrefix}.${application.id}`,
    );
    setSelectedResumeTemplateId(savedTemplateId || "classic_single");
    setSelectedResumeGenerationMode(
      isResumeGenerationMode(savedGenerationMode)
        ? savedGenerationMode
        : defaultResumeGenerationMode,
    );
    setResumeTemplateNotice("");
    setDocumentsLoaded(false);
    setMasterResumeLoaded(false);
    setCurrentMasterResume(null);
    setDocuments([]);
    setDocumentError("");
    setResumeTailoringProgress(null);
    const controller = new AbortController();
    Promise.all([
      fetchWithTimeout(`${apiBaseUrl}/documents?applicationId=${encodeURIComponent(application.id)}`, { signal: controller.signal }),
      fetchWithTimeout(`${apiBaseUrl}/documents/templates/library`, { signal: controller.signal }),
      fetchWithTimeout(`${apiBaseUrl}/resume-templates`, { cache: "no-store", signal: controller.signal }),
      fetchWithTimeout(`${apiBaseUrl}/assistant/config`, { signal: controller.signal }),
      fetchWithTimeout(`${apiBaseUrl}/profile/master-resume`, { cache: "no-store", signal: controller.signal }),
    ])
      .then(async ([documentsResponse, templatesResponse, resumeTemplatesResponse, aiConfigurationResponse, masterResumeResponse]) => {
        if (!documentsResponse.ok || !templatesResponse.ok || !resumeTemplatesResponse.ok || !aiConfigurationResponse.ok || (!masterResumeResponse.ok && masterResumeResponse.status !== 404)) throw new Error("Application documents are temporarily unavailable");
        const loadedDocuments = await documentsResponse.json() as GeneratedDocument[];
        const loadedTemplates = await templatesResponse.json() as DocumentTemplate[];
        const loadedResumeTemplates = await resumeTemplatesResponse.json() as ResumeTemplate[];
        const loadedAiConfiguration = await aiConfigurationResponse.json() as AiConfiguration;
        const loadedMasterResume = masterResumeResponse.ok
          ? await masterResumeResponse.json() as CurrentMasterResume
          : null;
        setDocuments(loadedDocuments);
        setTemplates(loadedTemplates.filter((template) => template.type === "cover_letter"));
        setResumeTemplates(loadedResumeTemplates);
        const preferredResumeTemplate =
          loadedResumeTemplates.find(
            (template) => template.id === savedTemplateId,
          ) ??
          loadedResumeTemplates.find(
            (template) => template.id === "classic_single",
          ) ??
          loadedResumeTemplates[0];
        setSelectedResumeTemplateId(preferredResumeTemplate?.id ?? "");
        if (
          savedTemplateId &&
          !loadedResumeTemplates.some(
            (template) => template.id === savedTemplateId,
          )
        ) {
          setResumeTemplateNotice(
            "Your previously selected resume template is no longer available. An available built-in template was selected.",
          );
          if (preferredResumeTemplate) {
            window.localStorage.setItem(
              `${resumeTemplateStorageKeyPrefix}.${application.id}`,
              preferredResumeTemplate.id,
            );
          } else {
            window.localStorage.removeItem(
              `${resumeTemplateStorageKeyPrefix}.${application.id}`,
            );
          }
        }
        setAiConfiguration(loadedAiConfiguration);
        setCurrentMasterResume(loadedMasterResume);
        setMasterResumeLoaded(true);
        setDocumentsLoaded(true);
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setApiHealth("unavailable");
        setMasterResumeLoaded(true);
        setDocumentError(apiUnavailableMessage(error, "Application documents are temporarily unavailable"));
      });
    return () => controller.abort();
  }, [application, apiRetryVersion]);

  const latestResume = useMemo(
    () => documents.find((document) => document.type === "tailored_resume"),
    [documents],
  );
  const latestCoverLetter = useMemo(
    () => documents.find((document) => document.type === "cover_letter"),
    [documents],
  );
  const latestResumeVersion = latestResume?.versions.find(
    (version) => version.version === latestResume.currentVersion,
  );
  const latestResumeArtifact = latestResumeVersion?.artifact;
  const latestResumeIsPdf =
    latestResumeArtifact?.contentType === "application/pdf";
  const coverLetterTemplate = useMemo(
    () => templates.find((template) => template.builtIn) ?? null,
    [templates],
  );
  const analysisStatus = getAiMatchAnalysisStatus(application?.job.aiMatch);
  const hasCurrentAnalysis = analysisStatus === "current";
  const isAnalysisOutdated = analysisStatus === "outdated";
  const isLegacyAnalysis = isLegacyAiMatch(application?.job.aiMatch);
  const applicationReview = useMemo(
    () => application ? buildSavedApplicationReview(application.job) : "",
    [application],
  );
  const applicationGuide = hasCurrentAnalysis ? application?.job.aiMatch?.applicationGuide : undefined;
  const applicationClarificationQuestions = useMemo(
    () => (applicationGuide?.clarificationQuestions ?? []).filter(
      (question) => !coverLetterContextQuestionIds.has(question.id),
    ),
    [applicationGuide?.clarificationQuestions],
  );
  const clarificationQuestions = useMemo(
    () => [...applicationClarificationQuestions, ...coverLetterContextQuestions],
    [applicationClarificationQuestions],
  );
  const resumeRelevantConfirmationIds = useMemo(
    () => new Set(
      applicationClarificationQuestions.map((question) => question.id),
    ),
    [applicationClarificationQuestions],
  );
  const unansweredBlockingQuestions = clarificationQuestions.filter(
    (question) => question.blocking && !isCandidateConfirmationComplete(question, candidateConfirmations[question.id]),
  );
  const hasIncompleteBlockingConfirmations = unansweredBlockingQuestions.length > 0;
  const hasOversizedConfirmation = clarificationQuestions.some(
    (question) => (candidateConfirmations[question.id]?.exampleText.trim().length ?? 0) > confirmationAnswerMaxChars,
  );
  const coverLetterRecipient = candidateConfirmations[coverLetterRecipientQuestion.id];
  const coverLetterRecipientName = coverLetterRecipient?.exampleText ?? "";
  const coverLetterRecipientNameComplete = (
    coverLetterRecipient?.response !== "yes"
    || coverLetterRecipientName.trim().split(/\s+/).filter(Boolean).length >= 2
  );
  const coverLetterCompanyContact = candidateConfirmations[coverLetterCompanyContactQuestion.id];
  const coverLetterCompanyContactName = coverLetterCompanyContact?.exampleText ?? "";
  const coverLetterCompanyContactNameComplete = (
    coverLetterCompanyContact?.response !== "yes"
    || coverLetterCompanyContactName.trim().split(/\s+/).filter(Boolean).length >= 2
  );
  const coverLetterNamesComplete = (
    coverLetterRecipientNameComplete
    && coverLetterCompanyContactNameComplete
  );
  const vacancyLanguage = applicationGuide?.language || (application ? detectLegacyJobLanguage(application.job) : "");
  const effectiveLanguage = languageMode === "auto" ? vacancyLanguage : languageMode;
  const documentLanguage = effectiveLanguage || "English";
  useEffect(() => {
    setLanguageMode("auto");
    setAnalysisTab("overview");
    setActiveWorkspaceStep(
      hasCurrentApplicationGuide(application?.job.aiMatch) ? "create" : "review",
    );
    setDocumentChatTarget("question");
    setDocumentChatInput("");
    setDocumentChatMessages([]);
    setIsDocumentChatResponding(false);
    if (!application) {
      setCandidateConfirmations({});
      setConfirmationsDirty(false);
      return;
    }
    const controller = new AbortController();
    const applicationId = application.id;
    const legacyStorageKey = `tasko.application-confirmations.${applicationId}`;
    setCandidateConfirmations({});
    setConfirmationsDirty(false);
    setConfirmationSyncStatus("loading");
    setConfirmationSyncMessage("");

    async function loadCandidateConfirmations() {
      try {
        const response = await fetchWithTimeout(
          `${apiBaseUrl}/applications/${encodeURIComponent(applicationId)}/confirmations`,
          { cache: "no-store", signal: controller.signal },
        );
        if (!response.ok && response.status !== 404) {
          throw new Error(await readApiError(response, "Candidate confirmations could not be loaded"));
        }
        const storedConfirmations = response.ok ? await response.json() as CandidateConfirmation[] : [];
        const questionsById = new Map(clarificationQuestions.map((question) => [question.id, question]));
        const backendNeedsSync = storedConfirmations.some((confirmation) => {
          const question = questionsById.get(confirmation.questionId);
          return !question || confirmation.requirement !== question.requirement || confirmation.blocking !== question.blocking;
        });
        const backendById = Object.fromEntries(storedConfirmations.flatMap((confirmation) => {
          const question = questionsById.get(confirmation.questionId);
          if (!question) return [];
          return [[confirmation.questionId, {
            ...confirmation,
            requirement: question.requirement,
            blocking: question.blocking,
          }]];
        }));
        let legacyById: Record<string, CandidateConfirmation> = {};
        try {
          const storedLegacyAnswers = window.localStorage.getItem(legacyStorageKey);
          legacyById = importLegacyCandidateConfirmations(
            storedLegacyAnswers ? JSON.parse(storedLegacyAnswers) : null,
            clarificationQuestions,
          );
        } catch {
          legacyById = {};
        }

        const missingLegacyConfirmations = Object.fromEntries(
          Object.entries(legacyById).filter(([questionId]) => !backendById[questionId]),
        );
        const shouldSync = Object.keys(missingLegacyConfirmations).length > 0 || backendNeedsSync;
        setCandidateConfirmations({ ...missingLegacyConfirmations, ...backendById });
        setConfirmationsDirty(shouldSync);
        setConfirmationSyncStatus(shouldSync ? "unsaved" : "saved");
        setConfirmationSyncMessage(Object.keys(missingLegacyConfirmations).length > 0 ? "Legacy answers imported — checking before backend save" : backendNeedsSync ? "Requirements changed — updating saved answers" : "");
        if (Object.keys(legacyById).length > 0 && Object.keys(missingLegacyConfirmations).length === 0) {
          window.localStorage.removeItem(legacyStorageKey);
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setApiHealth("unavailable");
        setConfirmationSyncStatus("error");
        setConfirmationSyncMessage(apiUnavailableMessage(error, "Candidate confirmations could not be loaded"));
      }
    }

    void loadCandidateConfirmations();
    return () => controller.abort();
  }, [application?.id, application?.job.aiMatch?.updatedAt, apiRetryVersion]);

  useEffect(() => {
    if (!application || !confirmationsDirty) return;
    if (hasOversizedConfirmation) {
      setConfirmationSyncStatus("unsaved");
      setConfirmationSyncMessage(
        `Shorten examples to ${confirmationAnswerMaxChars.toLocaleString()} characters`,
      );
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(async () => {
      setConfirmationSyncStatus("saving");
      setConfirmationSyncMessage("");
      try {
        const confirmations = clarificationQuestions.flatMap((question) => {
          const confirmation = candidateConfirmations[question.id];
          if (!confirmation) return [];
          return [{
            questionId: confirmation.questionId,
            response: confirmation.response,
            exampleText: confirmation.exampleText,
          }];
        });
        const response = await fetchWithTimeout(
          `${apiBaseUrl}/applications/${encodeURIComponent(application.id)}/confirmations`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirmations }),
            signal: controller.signal,
          },
        );
        if (!response.ok) throw new Error(await readApiError(response, "Candidate confirmations could not be saved"));
        const savedConfirmations = await response.json() as CandidateConfirmation[];
        setCandidateConfirmations(Object.fromEntries(savedConfirmations.map((confirmation) => [confirmation.questionId, confirmation])));
        setConfirmationsDirty(false);
        setConfirmationSyncStatus("saved");
        setConfirmationSyncMessage("");
        window.localStorage.removeItem(`tasko.application-confirmations.${application.id}`);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setApiHealth("unavailable");
        setConfirmationSyncStatus("error");
        setConfirmationSyncMessage(apiUnavailableMessage(error, "Candidate confirmations could not be saved"));
      }
    }, 600);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [application, candidateConfirmations, clarificationQuestions, confirmationsDirty, hasOversizedConfirmation]);

  if (!application) {
    return (
      <section className="grid min-w-0 flex-1 place-items-center p-6">
        <div className="panel max-w-md p-6 text-center">
          <FileText className="mx-auto h-8 w-8 text-muted" />
          <h1 className="mt-3 text-lg font-bold text-foreground">No application selected</h1>
          <Button className="mt-4 bg-accent text-foreground" onClick={onBack}><ArrowLeft className="h-4 w-4" /> Back to {backLabel.toLowerCase()}</Button>
        </div>
      </section>
    );
  }

  const activeApplication = application;
  const documentChatTargetReady = documentChatTarget === "question"
    ? documentsLoaded
    : documentChatTarget === "tailored_resume"
      ? Boolean(latestResume && currentMasterResume && resumeTemplates.length)
      : Boolean(
        latestCoverLetter
        && coverLetterTemplate
        && coverLetterNamesComplete,
      );
  const documentChatPlaceholder = documentChatTarget === "question"
    ? "Ask anything about this application, CV, or cover letter…"
    : documentChatTarget === "tailored_resume"
      ? "What should AI change or emphasize in the CV?"
      : "What should AI change in the cover letter?";
  const documentChatUnavailableMessage = documentChatTarget === "tailored_resume"
    ? "Generate the CV before requesting a revision."
    : documentChatTarget === "cover_letter"
      ? "Generate the cover letter and complete the contact names before requesting a revision."
      : "Application context is still loading.";
  const jobUrl = normalizeJobsChJobUrl(
    activeApplication.job.applyUrl || activeApplication.job.sourceUrl || "",
  );
  const profileReady = Boolean(profile.name && (profile.experience || profile.resume_file_name));
  const confirmationsReady = hasCurrentAnalysis
    && unansweredBlockingQuestions.length === 0
    && !hasOversizedConfirmation
    && !confirmationsDirty
    && confirmationSyncStatus === "saved";
  const documentChatCanSubmit = documentChatTarget === "question"
    ? documentChatTargetReady
    : documentChatTargetReady && Boolean(applicationReview) && confirmationsReady;
  const analysisRequiredLabel = isAnalysisOutdated ? "Refresh analysis first" : "AI Match required";
  const hasNewerResumeConfirmation = Boolean(
    latestResume
    && Object.values(candidateConfirmations).some((confirmation) => (
      resumeRelevantConfirmationIds.has(confirmation.questionId)
      &&
      confirmation.updatedAt
      && new Date(confirmation.updatedAt).getTime()
        > new Date(latestResume.updatedAt).getTime()
    )),
  );
  const isResumeOutdated = Boolean(
    latestResume
    && (
      isGeneratedDocumentOutdated(
        latestResume.generationFingerprint,
        latestResume.currentGenerationFingerprint,
      )
      || (
        latestResumeArtifact?.contentType === "application/pdf"
        && resumeArtifactGenerationMode(latestResumeArtifact)
          !== selectedResumeGenerationMode
      )
      || hasNewerResumeConfirmation
      || (
        generatedDocumentLanguage(latestResume) !== null
        && generatedDocumentLanguage(latestResume) !== documentLanguage
      )
    ),
  );
  const isCoverLetterOutdated = Boolean(
    latestCoverLetter
    && (
      isGeneratedDocumentOutdated(
        latestCoverLetter.generationFingerprint,
        latestCoverLetter.currentGenerationFingerprint,
      )
      || (
        generatedDocumentLanguage(latestCoverLetter) !== null
        && generatedDocumentLanguage(latestCoverLetter) !== documentLanguage
      )
    ),
  );
  const resumeReady = getGeneratedDocumentReadiness(latestResume, isResumeOutdated).ready;
  const coverLetterReady = getGeneratedDocumentReadiness(latestCoverLetter, isCoverLetterOutdated).ready;
  const checklist = [
    { label: "Candidate profile", ready: profileReady },
    { label: "Vacancy analysis", ready: hasCurrentAnalysis },
    { label: "Required confirmations", ready: confirmationsReady },
    { label: "Tailored CV", ready: resumeReady },
    { label: "Cover letter", ready: coverLetterReady },
    { label: "Application link", ready: Boolean(jobUrl) },
  ];
  const readyCount = checklist.filter((item) => item.ready).length;
  const progress = Math.round((readyCount / checklist.length) * 100);
  const preparationSteps = [
    { id: "review" as const, label: "Review fit", detail: isAnalysisOutdated ? "Analysis outdated" : "Positioning and requirements", ready: hasCurrentAnalysis, icon: Target },
    { id: "confirm" as const, label: "Confirm details", detail: !hasCurrentAnalysis ? "Refresh analysis first" : hasOversizedConfirmation ? "Shorten a long answer" : unansweredBlockingQuestions.length ? `${unansweredBlockingQuestions.length} answer${unansweredBlockingQuestions.length === 1 ? "" : "s"} required` : "Evidence confirmed", ready: confirmationsReady, icon: MessageSquareText },
    { id: "create" as const, label: "Create documents", detail: resumeReady && coverLetterReady ? "Application pack ready" : "CV and cover letter", ready: resumeReady && coverLetterReady, icon: FileText },
    { id: "final" as const, label: "Final review", detail: progress === 100 ? "Ready to submit" : `${readyCount} of ${checklist.length} checks ready`, ready: progress === 100, icon: ShieldCheck },
  ];

  function updateCandidateConfirmation(
    question: NonNullable<ApplicationGuide["clarificationQuestions"]>[number],
    updates: Partial<Pick<CandidateConfirmation, "response" | "exampleText">>,
  ) {
    setCandidateConfirmations((currentConfirmations) => {
      const current = currentConfirmations[question.id];
      const next: CandidateConfirmation = {
        questionId: question.id,
        requirement: question.requirement,
        response: updates.response ?? current?.response ?? "yes",
        exampleText: updates.exampleText ?? current?.exampleText ?? "",
        blocking: question.blocking,
        updatedAt: current?.updatedAt ?? "",
      };
      return { ...currentConfirmations, [question.id]: next };
    });
    setConfirmationsDirty(true);
    setConfirmationSyncStatus("unsaved");
    setConfirmationSyncMessage("");
  }

  async function askAssistant(
    message: string,
    generationContext?: {
      applicationId: string;
      templateId: string;
      documentType: GeneratedDocument["type"];
      targetLanguage: "English" | "German";
    },
  ) {
    if (!message.trim()) return { message: "", generationArtifactId: "" };
    const response = await fetch(`${apiBaseUrl}/assistant/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        threadId: createId(`application-workspace-${activeApplication.id}`),
        message,
        contextKind: "application",
        contextId: activeApplication.id,
        ...(generationContext ? { generationContext } : {}),
      }),
    });
    if (response.status === 413) {
      throw new Error(await readApiError(response, "The document-generation request is too large. Shorten the revision instruction and try again."));
    }
    if (!response.ok) {
      const message = await readApiError(response, "AI request failed");
      if (response.status === 429 || response.status >= 500) {
        throw new RetryablePackError(message);
      }
      throw new Error(message);
    }
    const payload = await response.json() as {
      message?: string;
      metadata?: { generationArtifactId?: string };
    };
    return {
      message: payload.message?.trim() ?? "",
      generationArtifactId: payload.metadata?.generationArtifactId?.trim() ?? "",
    };
  }

  async function generateCoverLetterDraft(
    onRetry?: (attempt: number) => void,
    correction?: DocumentGenerationCorrection,
    userInstruction = "",
  ): Promise<CoverLetterDraftResult> {
    if (!documentsLoaded) throw new Error("Document history is still loading");
    if (!coverLetterTemplate) {
      throw new Error("The built-in cover letter template is unavailable");
    }
    if (!applicationReview) {
      throw new Error(isAnalysisOutdated ? "Refresh the outdated analysis before generating documents" : "Run AI Match before generating documents");
    }
    if (unansweredBlockingQuestions.length > 0) {
      throw new Error("Answer the required confirmation questions before generating documents");
    }
    if (confirmationsDirty || confirmationSyncStatus !== "saved") {
      throw new Error("Wait until candidate confirmations are saved before generating documents");
    }
    const oversizedConfirmation = clarificationQuestions.find(
      (question) => (candidateConfirmations[question.id]?.exampleText.trim().length ?? 0) > confirmationAnswerMaxChars,
    );
    if (oversizedConfirmation) {
      throw new Error(`Shorten the highlighted confirmation to ${confirmationAnswerMaxChars.toLocaleString()} characters before generating`);
    }
    const generationContext = {
      applicationId: activeApplication.id,
      templateId: coverLetterTemplate.id,
      documentType: "cover_letter" as const,
      targetLanguage: documentLanguage,
    };
    const invokeAssistant = async (prompt: string) => {
      const generate = () => askAssistant(ensureGenerationPromptFits(prompt), generationContext);
      return onRetry
        ? await retryPackOperation(generate, (attempt) => {
            onRetry(attempt);
          })
        : await generate();
    };

    const basePrompt = buildDocumentGenerationPrompt(documentLanguage);
    const requestedPrompt = userInstruction.trim()
      ? buildDocumentRevisionPrompt(basePrompt, userInstruction.trim())
      : basePrompt;
    let activeCorrection = correction;
    for (let attempt = 1; attempt <= emptyDraftRepairAttempts; attempt += 1) {
      const prompt = activeCorrection
        ? buildDocumentCorrectionPrompt(requestedPrompt, activeCorrection)
        : requestedPrompt;
      const assistantResult = await invokeAssistant(prompt);
      if (!assistantResult.message) throw new Error("AI returned an empty document");
      if (!assistantResult.generationArtifactId) {
        throw new Error("AI generation did not return a server artifact");
      }
      const replacementCount = structuredReplacementCount(assistantResult.message);
      if (replacementCount === null || replacementCount === 0) {
        if (attempt < emptyDraftRepairAttempts) {
          activeCorrection = {
            feedback: replacementCount === 0
              ? "The previous draft contained zero replacements and would produce an unchanged document. Create meaningful evidence-backed adaptations while preserving all unsupported or immutable text."
              : "The previous draft did not use the required structured replacements JSON. Return the exact requested JSON shape and make only evidence-backed edits to editable spans.",
            previousDraft: assistantResult.message,
          };
          continue;
        }
        throw new Error(noSafeDocumentChangesMessage("cover letter"));
      }
      return {
        draft: {
          ...(latestCoverLetter ? { documentId: latestCoverLetter.id } : {}),
          title: `Cover letter · ${activeApplication.job.title} · ${activeApplication.job.company}`,
          generationArtifactId: assistantResult.generationArtifactId,
        },
        generatedContent: assistantResult.message,
      };
    }
    throw new Error(noSafeDocumentChangesMessage("cover letter"));
  }

  async function generateResumePdf(
    allowDuringPack = false,
    revisionInstruction = "",
  ) {
    if (isGeneratingPack && !allowDuringPack) return false;
    if (!masterResumeLoaded) {
      setDocumentError("Master Resume is still loading");
      return false;
    }
    if (!currentMasterResume) {
      setDocumentError("Confirm a Master Resume in My Profile before tailoring");
      return false;
    }
    if (!resumeTemplates.some((template) => template.id === selectedResumeTemplateId)) {
      setDocumentError("Choose an available resume template");
      return false;
    }
    const attempt = 1;
    const generationMode = selectedResumeGenerationMode;
    const savedRenderSource = reusableResumeSource(
      latestResume,
      isResumeOutdated,
      generationMode,
    );
    setGenerationType("tailored_resume");
    setDocumentError("");
    const postStage = async <T extends { id: string }>(
      path: string,
      body: unknown,
      fallback: string,
      timeoutMs = AI_GENERATION_REQUEST_TIMEOUT_MS,
    ): Promise<T> => {
      const response = await fetchWithTimeout(
        `${apiBaseUrl}${path}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
        timeoutMs,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response, fallback));
      }
      return await response.json() as T;
    };
    const renderAndAttachFinalResume = async (
      source: ResumeRenderSource,
      reuseSavedFinalResume: boolean,
    ) => {
      setResumeTailoringProgress({
        mode: generationMode,
        stage: "rendering_pdf",
        status: "active",
        message: reuseSavedFinalResume
          ? "Rendering the saved finalResume with the selected template — no AI rerun"
          : "Rendering finalResume with the selected resume template",
        attempt,
      });
      const pdfResponse = await fetchWithTimeout(
        resumeRenderUrl(
          apiBaseUrl,
          source,
          "pdf",
          selectedResumeTemplateId,
        ),
        { cache: "no-store" },
        AI_GENERATION_REQUEST_TIMEOUT_MS,
      );
      if (!pdfResponse.ok) {
        const detail = await readApiError(pdfResponse, "PDF rendering failed");
        if (pdfResponse.status === 404) {
          handleResumeTemplateUnavailable(selectedResumeTemplateId);
          throw new Error(
            "The selected resume template was deleted or is no longer available. Choose another template.",
          );
        }
        throw new Error(detail);
      }
      const documentId = pdfResponse.headers.get("X-Rufina-Document-Id");
      if (!documentId) {
        throw new Error("PDF renderer did not return a saved document ID");
      }
      await pdfResponse.arrayBuffer();

      setResumeTailoringProgress({
        mode: generationMode,
        stage: "validating_pdf",
        status: "active",
        message: "Loading the server-validated PDF artifact",
        attempt,
      });
      const attachResponse = await fetchWithTimeout(
        `${apiBaseUrl}/documents/${encodeURIComponent(documentId)}/attachments`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ applicationId: activeApplication.id }),
        },
      );
      if (!attachResponse.ok) {
        throw new Error(await readApiError(attachResponse, "PDF could not be attached to the application"));
      }
      const saved = await attachResponse.json() as GeneratedDocument;
      setDocuments((current) => [
        saved,
        ...current.filter((document) => document.id !== saved.id),
      ]);
      setResumeTailoringProgress(
        completedResumeTailoringProgress(
          reuseSavedFinalResume
            ? "Saved finalResume rendered with the selected template"
            : "PDF rendered, validated, and saved",
          attempt,
          generationMode,
        ),
      );
      onDocumentAttached(activeApplication.id, {
        artifactId: saved.id,
        title: saved.title,
        fileName: documentFileName(saved),
        fileType: "application/pdf",
        uploadedAt: saved.updatedAt,
        downloadUrl: `${apiBaseUrl}/documents/${encodeURIComponent(saved.id)}/download`,
      });
      return true;
    };

    try {
      if (savedRenderSource && !revisionInstruction.trim()) {
        return await renderAndAttachFinalResume(
          savedRenderSource,
          true,
        );
      }
      if (generationMode === "imaginator") {
        setResumeTailoringProgress({
          mode: generationMode,
          stage: "imaginator_generation",
          status: "active",
          message:
            "Imaginator is building an idealized profile and then running an independent protected-fact audit",
          attempt,
        });
        const imaginator = await postStage<{ id: string }>(
          "/resume-tailoring/imaginator",
          {
            masterResumeId: currentMasterResume.masterResumeId,
            targetJobId: activeApplication.job.id,
            applicationId: activeApplication.id,
            generationMode,
            targetLanguage: documentLanguage,
            ...(revisionInstruction.trim()
              ? { revisionInstruction: revisionInstruction.trim() }
              : {}),
          },
          "Imaginator generation failed",
          AI_GENERATION_REQUEST_TIMEOUT_MS * 2,
        );
        setResumeTailoringProgress({
          mode: generationMode,
          stage: "immutable_validation",
          status: "active",
          message:
            "Employer, education, and identity claims passed the independent protected-fact audit",
          attempt,
        });
        return await renderAndAttachFinalResume(
          { kind: "imaginator", id: imaginator.id },
          false,
        );
      }

      setResumeTailoringProgress({
        mode: generationMode,
        stage: "recruiter_analysis",
        status: "active",
        message: "Recruiter analysis is reviewing the confirmed Master Resume",
        attempt,
      });
      const recruiter = await postStage<{ id: string }>(
        "/resume-tailoring/senior-recruiter-analysis",
        {
          masterResumeId: currentMasterResume.masterResumeId,
          targetJobId: activeApplication.job.id,
          applicationId: activeApplication.id,
          generationMode,
          targetLanguage: documentLanguage,
          ...(revisionInstruction.trim()
            ? { revisionInstruction: revisionInstruction.trim() }
            : {}),
        },
        "Senior recruiter analysis failed",
      );

      setResumeTailoringProgress({
        mode: generationMode,
        stage: "experience_rewrite",
        status: "active",
        message: "Experience rewrite is adapting verified achievements",
        attempt,
      });
      const rewrite = await postStage<{ id: string }>(
        "/resume-tailoring/experience-rewrite",
        {
          seniorRecruiterAnalysisId: recruiter.id,
          targetLanguage: documentLanguage,
        },
        "Experience rewrite failed",
      );

      setResumeTailoringProgress({
        mode: generationMode,
        stage: "ats_final_review",
        status: "active",
        message: "ATS final review is producing the only renderable finalResume",
        attempt,
      });
      const review = await postStage<{ id: string }>(
        "/resume-tailoring/ats-final-review",
        {
          experienceRewriteId: rewrite.id,
          targetLanguage: documentLanguage,
        },
        "ATS final review failed",
      );
      return await renderAndAttachFinalResume(
        { kind: "ats_final_review", id: review.id },
        false,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Resume tailoring failed";
      setResumeTailoringProgress((current) => current
        ? { ...current, status: "failed", message }
        : {
            mode: generationMode,
            stage: generationMode === "imaginator"
              ? "imaginator_generation"
              : "recruiter_analysis",
            status: "failed",
            message,
            attempt,
          });
      setDocumentError(message);
      return false;
    } finally {
      setGenerationType("");
    }
  }

  async function generateDocument(
    type: GeneratedDocument["type"],
    userInstruction = "",
    allowDuringPack = false,
  ) {
    if (type === "tailored_resume") {
      return await generateResumePdf(allowDuringPack, userInstruction);
    }
    if (isGeneratingPack && !allowDuringPack) return false;
    if (!coverLetterNamesComplete) {
      setDocumentError("Complete the selected cover-letter contact names before generating");
      return false;
    }
    setGenerationType(type);
    setDocumentError("");
    try {
      const generated = await generateCoverLetterDraft(
        undefined,
        undefined,
        userInstruction,
      );
      const { draft } = generated;
      const response = await fetch(
          latestCoverLetter
            ? `${apiBaseUrl}/documents/${encodeURIComponent(latestCoverLetter.id)}`
            : `${apiBaseUrl}/documents`,
          {
            method: latestCoverLetter ? "PATCH" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ...draft,
              applicationId: activeApplication.id,
              ...(latestCoverLetter ? { documentId: undefined } : {
                type: "cover_letter",
                jobId: activeApplication.job.id,
              }),
            }),
          },
        );
      if (!response.ok) {
        throw new Error(await readApiError(response, "Document save failed"));
      }
      const saved = await response.json() as GeneratedDocument;
      setDocuments((current) => [
        saved,
        ...current.filter((document) => document.id !== saved.id),
      ]);
      onDocumentAttached(activeApplication.id, {
        artifactId: saved.id,
        title: saved.title,
        fileName: documentFileName(saved),
        fileType: docxContentType,
        uploadedAt: saved.updatedAt,
        downloadUrl: `${apiBaseUrl}/documents/${encodeURIComponent(saved.id)}/download`,
      });
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Document generation failed";
      setDocumentError(message);
      return false;
    } finally {
      setGenerationType("");
    }
  }

  function requestAiGeneration(
    action: GeneratedDocument["type"] | "pack",
    instruction = "",
  ) {
    if (action === "pack") void generatePack();
    else void generateDocument(action, instruction);
  }

  async function runDocumentChatRevision(
    target: GeneratedDocument["type"],
    instruction: string,
  ) {
    const succeeded = await generateDocument(target, instruction);
    setDocumentChatMessages((current) => [
      ...current,
      {
        id: createId("document-chat-assistant"),
        role: "assistant",
        text: succeeded
          ? `Applied the instruction and saved a new ${target === "cover_letter" ? "cover letter" : "CV"} version.`
          : "I could not safely apply that instruction. Review the validation message and try a more specific evidence-backed request.",
      },
    ]);
  }

  async function runDocumentChatQuestion(question: string) {
    setIsDocumentChatResponding(true);
    try {
      const result = await askAssistant(
        `Answer this application question using the current vacancy, candidate profile, confirmations, and generated-document context. Do not claim that a document was changed. If the user is asking for a document change, explain that they should select Revise CV or Revise cover letter in this chat. USER QUESTION: ${question}`,
      );
      setDocumentChatMessages((current) => [
        ...current,
        {
          id: createId("document-chat-assistant"),
          role: "assistant",
          text: result.message || "I could not produce an answer from the available application context.",
        },
      ]);
    } catch (error) {
      setDocumentChatMessages((current) => [
        ...current,
        {
          id: createId("document-chat-assistant"),
          role: "assistant",
          text: error instanceof Error
            ? error.message
            : "I could not answer that question. Please try again.",
        },
      ]);
    } finally {
      setIsDocumentChatResponding(false);
    }
  }

  function applyDocumentChatInstruction() {
    const instruction = documentChatInput.trim();
    if (
      !instruction
      || generationType
      || isGeneratingPack
      || isDocumentChatResponding
      || !documentChatTargetReady
    ) return;
    setDocumentChatMessages((current) => [
      ...current,
      { id: createId("document-chat-user"), role: "user", text: instruction },
    ]);
    setDocumentChatInput("");
    if (documentChatTarget === "question") {
      void runDocumentChatQuestion(instruction);
    } else {
      void runDocumentChatRevision(documentChatTarget, instruction);
    }
  }

  async function generatePack() {
    if (isGeneratingPack || generationType) return;
    if (!coverLetterNamesComplete) {
      setDocumentError("Complete the selected cover-letter contact names before generating the application pack");
      return;
    }
    const packJobId = createId("application-pack");
    const updateProgress = (
      stage: PackStageId,
      status: PackProgressStatus,
      message: string,
      attempt = 1,
    ) => setPackProgress({ jobId: packJobId, stage, status, attempt, message });
    setIsGeneratingPack(true);
    setDocumentError("");
    try {
      updateProgress(
        "resume_generation",
        "active",
        selectedResumeGenerationMode === "imaginator"
          ? "Running Imaginator and locked-fact validation"
          : "Running the three mandatory resume-tailoring stages",
      );
      const resumeSaved = await generateResumePdf(true);
      if (!resumeSaved) {
        throw new Error("Resume PDF generation failed");
      }
      updateProgress(
        "resume_generation",
        "completed",
        selectedResumeGenerationMode === "imaginator"
          ? "Imaginator resume generation completed"
          : "Three-stage resume tailoring completed",
      );
      updateProgress(
        "resume_validation",
        "completed",
        "Bundled PDF rendered and validated",
      );

      updateProgress(
        "cover_letter_generation",
        "active",
        "Creating cover letter after PDF approval",
      );
      const coverSaved = await generateDocument("cover_letter", "", true);
      if (!coverSaved) {
        updateProgress(
          "cover_letter_generation",
          "partial",
          "Resume PDF saved; cover letter generation failed",
        );
        throw new Error("Resume PDF was saved, but cover letter generation failed");
      }
      updateProgress(
        "cover_letter_generation",
        "completed",
        "Cover letter generated and saved",
      );
      updateProgress(
        "saving",
        "completed",
        "Application PDF and cover letter are ready",
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Application pack generation failed";
      setPackProgress((current) => (
        current && current.jobId === packJobId && current.status !== "failed"
          ? { ...current, status: "failed", message }
          : current
      ));
      setDocumentError(message);
    } finally {
      setGenerationType("");
      setIsGeneratingPack(false);
    }
  }

  async function restoreDocumentVersion(document: GeneratedDocument, version: number) {
    const restoreKey = `${document.id}:${version}`;
    setRestoringVersionKey(restoreKey);
    setDocumentError("");
    try {
      const response = await fetch(
        `${apiBaseUrl}/documents/${encodeURIComponent(document.id)}/restore`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ version }),
        },
      );
      if (!response.ok) throw new Error(await readApiError(response, "Document version could not be restored"));
      const restored = await response.json() as GeneratedDocument;
      setDocuments((current) => [
        restored,
        ...current.filter((currentDocument) => currentDocument.id !== restored.id),
      ]);
      onDocumentAttached(activeApplication.id, {
        artifactId: restored.id,
        title: restored.title,
        fileName: documentFileName(restored),
        fileType: docxContentType,
        uploadedAt: restored.updatedAt,
        downloadUrl: `${apiBaseUrl}/documents/${encodeURIComponent(restored.id)}/download`,
      });
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : "Document version could not be restored");
    } finally {
      setRestoringVersionKey("");
    }
  }

  async function loadMoreDocumentVersions(document: GeneratedDocument) {
    setLoadingVersionHistoryId(document.id);
    setDocumentError("");
    try {
      const response = await fetch(
        `${apiBaseUrl}/documents/${encodeURIComponent(document.id)}/versions?offset=${document.versions.length}&limit=20`,
      );
      if (!response.ok) throw new Error(await readApiError(response, "Version history could not be loaded"));
      const page = await response.json() as {
        items: GeneratedDocumentVersion[];
        total: number;
      };
      setDocuments((current) => current.map((item) => {
        if (item.id !== document.id) return item;
        const versions = [...item.versions, ...page.items].filter(
          (version, index, all) => all.findIndex((candidate) => candidate.id === version.id) === index,
        );
        return {
          ...item,
          versions,
          versionsTotal: page.total,
          versionsHasMore: versions.length < page.total,
        };
      }));
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : "Version history could not be loaded");
    } finally {
      setLoadingVersionHistoryId("");
    }
  }

  async function deleteGeneratedDocument(document: GeneratedDocument) {
    if (!window.confirm(`Delete ${document.title} and all of its versions?`)) return;
    setDeletingDocumentId(document.id);
    setDocumentError("");
    try {
      const response = await fetch(`${apiBaseUrl}/documents/${encodeURIComponent(document.id)}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response, "Document could not be deleted"));
      setDocuments((current) => current.filter((item) => item.id !== document.id));
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : "Document could not be deleted");
    } finally {
      setDeletingDocumentId("");
    }
  }

  function requestAdvice(prompt: string) {
    setAdvicePrompt(prompt);
    setIsLoadingAdvice(false);
    setAdvice(buildGroundedAdvice(prompt, applicationGuide));
  }

  return (
    <>
    <section className="job-scroll application-workspace min-w-0 flex-1 overflow-y-auto px-3 py-4 sm:px-5 xl:px-7">
      <div className="mx-auto max-w-[1420px]">
        <button type="button" onClick={onBack} className="mb-4 inline-flex items-center gap-2 text-xs font-semibold text-muted transition hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> {backLabel}
        </button>

        <header className="application-hero overflow-hidden rounded-2xl border border-border">
          <div className="relative grid gap-5 px-5 py-5 sm:px-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[10px] font-black uppercase tracking-[0.14em] text-accent">Application workspace</span>
                <span className="sr-only">Application prep</span>
                <span className="text-foreground/20">/</span>
                <span className="rounded-full border border-border bg-[#fff8f1] px-2.5 py-1 text-[10px] font-bold capitalize text-[#4a4a47]">{application.status === "draft" ? "In progress" : application.status}</span>
              </div>
              <h1 className="mt-3 max-w-4xl text-xl font-bold leading-tight tracking-[-0.02em] text-foreground sm:text-2xl">{application.job.title}</h1>
              <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-[#4a4a47]">
                <span className="text-[#1d1e1c]">{application.job.company}</span><span className="text-foreground/25">/</span><span>{application.job.location}</span><span className="text-foreground/25">/</span><span>{application.job.type}</span>
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 lg:justify-end">
              <div className="mr-1 flex h-11 items-center gap-2 rounded-xl border border-success/20 bg-success/[0.055] px-3.5">
                <CheckCircle2 className="h-4 w-4 text-success" />
                <div><p className="text-[8px] font-black uppercase tracking-[0.12em] text-[#615f5c]">Match</p><p className="text-sm font-black text-success">{application.job.match}%</p></div>
              </div>
              <Button variant="ghost" disabled={!jobUrl} onClick={() => jobUrl && window.open(jobUrl, "_blank", "noopener,noreferrer")} className="h-11 rounded-xl border border-border bg-[#fff8f1] px-4 text-xs text-[#1d1e1c] hover:bg-[#fff3e8] disabled:opacity-45">
                <ExternalLink className="h-4 w-4" /> View vacancy
              </Button>
            </div>
          </div>
          <nav className="grid border-t border-border bg-black/15 sm:grid-cols-2 xl:grid-cols-4" aria-label="Application preparation steps">
            {preparationSteps.map((step, index) => {
              const StepIcon = step.icon;
              return (
                <button
                  key={step.id}
                  type="button"
                  aria-current={activeWorkspaceStep === step.id ? "step" : undefined}
                  onClick={() => setActiveWorkspaceStep(step.id)}
                  className={cn(
                    "group relative flex min-w-0 items-center gap-3 border-border px-5 py-4 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/45 xl:border-r xl:last:border-r-0",
                    index > 0 && "border-t sm:border-t-0",
                    index === 2 && "sm:border-t xl:border-t-0",
                    activeWorkspaceStep === step.id ? "bg-[#fff8f1]" : "hover:bg-[#fff3e8]",
                  )}
                >
                  <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full border text-[11px] font-black transition", activeWorkspaceStep === step.id ? "border-accent bg-accent text-foreground" : step.ready ? "border-success/25 bg-success/10 text-success" : "border-border bg-[#fff8f1] text-[#615f5c]")}>{activeWorkspaceStep === step.id ? index + 1 : step.ready ? <Check className="h-4 w-4" /> : <StepIcon className="h-3.5 w-3.5" />}</span>
                  <span className="min-w-0"><span className={cn("block truncate text-xs font-bold", activeWorkspaceStep === step.id ? "text-foreground" : step.ready ? "text-[#1d1e1c]" : "text-[#4a4a47]")}>{step.label}</span><span className="mt-0.5 block truncate text-[10px] text-[#615f5c]">{step.detail}</span></span>
                  {activeWorkspaceStep === step.id ? <span className="absolute inset-x-5 bottom-0 h-0.5 rounded-full bg-accent" /> : null}
                </button>
              );
            })}
          </nav>
        </header>

        <div className="mt-5 grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_330px]">
          <main className="min-w-0 space-y-5">
            <div className={cn(activeWorkspaceStep !== "review" && "hidden")}>
            <section className="workspace-card overflow-hidden">
              <div className="flex flex-col gap-4 border-b border-border px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                <div className="flex items-start gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-accent/12 text-accent"><Target className="h-[18px] w-[18px]" /></span>
                  <div><p className="text-[10px] font-black uppercase tracking-[0.14em] text-accent">01 · Understand the role</p><h2 className="mt-1 text-lg font-bold tracking-[-0.01em] text-foreground">Your application angle</h2><p className="mt-1 text-xs leading-5 text-muted">Review the recommendation before generating any documents.</p></div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" variant="ghost" disabled={isAnalysisRefreshing} onClick={() => onRefreshAnalysis(activeApplication.id)} className={cn("h-11 rounded-xl border px-3 text-[11px] font-bold", isAnalysisOutdated ? "border-accent/25 bg-accent/10 text-accent hover:bg-accent/10" : "border-border bg-[#fff8f1] text-[#1d1e1c] hover:bg-[#fff3e8]")}>{isAnalysisRefreshing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}{isAnalysisRefreshing ? "Updating…" : isAnalysisOutdated ? "Update analysis" : "Refresh analysis"}</Button>
                </div>
              </div>

              {applicationGuide ? (
                <div className="p-5 sm:p-6">
                  <article className="relative overflow-hidden rounded-2xl border border-accent/20 bg-gradient-to-br from-accent/[0.09] via-white/[0.025] to-transparent p-5 sm:p-6">
                    <div className="absolute -right-16 -top-20 h-52 w-52 rounded-full bg-accent/10 blur-3xl" />
                    <div className="relative grid gap-5 lg:grid-cols-[minmax(0,1fr)_240px] lg:items-start">
                      <div><p className="text-[10px] font-black uppercase tracking-[0.14em] text-[#e95300]">Recommended narrative</p><p className="mt-3 text-base font-bold leading-7 text-foreground sm:text-lg">{applicationGuide.roleMission || activeApplication.job.overview || `Succeed as ${activeApplication.job.title}.`}</p><p className="mt-3 max-w-3xl text-sm leading-6 text-[#4a4a47]">{applicationGuide.positioning}</p></div>
                      <div className="rounded-xl border border-border bg-black/20 p-4">
                        <div className="flex items-center justify-between gap-2"><span className="text-[9px] font-black uppercase tracking-[0.1em] text-muted">Analysis status</span><span className={cn("rounded-full border px-2 py-1 text-[8px] font-black uppercase tracking-wide", applicationGuide.readiness === "ready" ? "border-success/30 bg-success/10 text-success" : applicationGuide.readiness === "weak_fit" ? "border-accent/25 bg-accent/10 text-accent" : "border-accent/25 bg-accent/10 text-accent")}>{(applicationGuide.readiness ?? "needs_confirmation").replace("_", " ")}</span></div>
                        <div className="mt-4 flex flex-wrap gap-1.5">{(applicationGuide.keywords ?? []).slice(0, 8).map((keyword) => <span key={keyword} className="rounded-md border border-border bg-[#fff8f1] px-2 py-1 text-[9px] font-semibold text-[#4a4a47]">{keyword}</span>)}</div>
                        <dl className="mt-4 grid gap-2 border-t border-border pt-3 text-[9px]">
                          <div className="flex items-center justify-between gap-3"><dt className="font-bold uppercase tracking-wide text-muted">Revision</dt><dd className="max-w-[145px] truncate font-mono text-[#1d1e1c]" title={application.job.aiMatch?.revision}>{application.job.aiMatch?.revision || "Unavailable"}</dd></div>
                          <div className="flex items-center justify-between gap-3"><dt className="font-bold uppercase tracking-wide text-muted">Fingerprint</dt><dd className="max-w-[145px] truncate font-mono text-[#1d1e1c]" title={application.job.aiMatch?.fingerprint}>{application.job.aiMatch?.fingerprint || "Unavailable"}</dd></div>
                        </dl>
                      </div>
                    </div>
                  </article>

                  <div className="mt-5 flex gap-1 overflow-x-auto rounded-xl border border-border bg-black/20 p-1" role="tablist" aria-label="Application analysis">
                    {[
                      { id: "overview" as const, label: "Role overview" },
                      { id: "evidence" as const, label: `Evidence map${applicationGuide.evidenceMatrix?.length ? ` · ${applicationGuide.evidenceMatrix.length}` : ""}` },
                      { id: "strategy" as const, label: "Document strategy" },
                    ].map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={analysisTab === tab.id} onClick={() => setAnalysisTab(tab.id)} className={cn("min-w-fit flex-1 rounded-lg px-4 py-2.5 text-[11px] font-bold transition", analysisTab === tab.id ? "bg-[#fff8f1] text-foreground shadow-sm" : "text-muted hover:bg-[#fff3e8] hover:text-foreground")}>{tab.label}</button>)}
                  </div>

                  {analysisTab === "overview" ? (
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      {[
                        { label: "What they care about", values: applicationGuide.hiringPriorities, tone: "text-[#e95300]" },
                        { label: "Must have", values: applicationGuide.mustHave, tone: "text-foreground" },
                        { label: "Advantage", values: applicationGuide.niceToHave, tone: "text-accent" },
                        { label: "Constraints to verify", values: applicationGuide.hardConstraints, tone: "text-accent" },
                      ].map((group) => <article key={group.label} className="rounded-xl border border-border bg-[#fff8f1] p-4"><h3 className={cn("text-[10px] font-black uppercase tracking-[0.11em]", group.tone)}>{group.label}</h3>{group.values?.length ? <ul className="mt-3 space-y-2 text-xs leading-5 text-[#4a4a47]">{group.values.map((value) => <li key={value} className="flex gap-2.5"><CircleDot className="mt-1 h-3 w-3 shrink-0 text-[#615f5c]" /><span>{value}</span></li>)}</ul> : <p className="mt-3 text-xs text-muted">Nothing critical identified.</p>}</article>)}
                      <article className="rounded-xl border border-success/15 bg-success/[0.035] p-4 md:col-span-2"><h3 className="text-[10px] font-black uppercase tracking-[0.11em] text-success">Why your profile fits</h3><div className="mt-3 grid gap-2 sm:grid-cols-2">{(application.job.aiMatch?.reasons.length ? application.job.aiMatch.reasons : application.job.skills.slice(0, 4).map((skill) => `${skill} aligns with this role.`)).slice(0, 4).map((reason) => <div key={reason} className="flex gap-2 text-xs leading-5 text-[#4a4a47]"><Check className="mt-1 h-3.5 w-3.5 shrink-0 text-success" /><span>{reason}</span></div>)}</div></article>
                    </div>
                  ) : null}

                  {analysisTab === "evidence" ? (
                    <div className="mt-4 overflow-hidden rounded-xl border border-border bg-black/15">
                      {applicationGuide.evidenceMatrix?.length ? (
                        <div className="divide-y divide-white/[0.07]">
                          {applicationGuide.evidenceMatrix.map((item) => {
                            const meta = evidenceStatusMeta(item.status);
                            return (
                              <article key={`${item.requirement}-${item.status}`} className="grid gap-3 px-4 py-4 md:grid-cols-[minmax(150px,0.7fr)_minmax(0,1.3fr)_auto] md:items-start">
                                <div><p className="text-xs font-bold text-foreground">{item.requirement}</p><p className="mt-1 text-[8px] font-black uppercase tracking-wider text-muted">{item.importance}</p></div>
                                <div>
                                  <p className="text-[11px] leading-5 text-[#4a4a47]">{item.evidence || "No verified evidence found in the profile."}</p>
                                  {item.action ? <p className="mt-1 text-[10px] leading-4 text-muted"><span className="font-bold text-[#1d1e1c]">Next:</span> {item.action}</p> : null}
                                  {item.sources?.length ? <div className="mt-2 space-y-1">{item.sources.map((source) => <p key={source.id} className="rounded-md border border-success/15 bg-success/[0.035] px-2 py-1.5 text-[9px] leading-4 text-[#4a4a47]"><span className="font-bold text-success">{source.label}:</span> “{source.excerpt}”</p>)}</div> : null}
                                </div>
                                <span className={cn("w-fit rounded-full border px-2 py-1 text-[8px] font-black uppercase tracking-wide", meta.className)}>{meta.label}</span>
                              </article>
                            );
                          })}
                        </div>
                      ) : <p className="p-6 text-center text-xs text-muted">No evidence map is available for this vacancy.</p>}
                    </div>
                  ) : null}

                  {analysisTab === "strategy" ? (
                    <div className="mt-4 space-y-3">
                      <div className="grid gap-3 lg:grid-cols-2">
                        <article className="rounded-xl border border-border bg-[#fff8f1] p-5"><div className="flex items-center gap-2"><FileText className="h-4 w-4 text-accent" /><h3 className="text-sm font-bold text-foreground">CV direction</h3></div><p className="mt-3 text-xs leading-5 text-[#1d1e1c]">{applicationGuide.resumePlan?.summaryFocus || applicationGuide.cvImprovements?.[0]}</p>{applicationGuide.resumePlan?.targetHeadline ? <p className="mt-3 rounded-lg bg-[#fff8f1] px-3 py-2 text-[10px] leading-4 text-muted"><span className="font-bold text-foreground">Headline:</span> {applicationGuide.resumePlan.targetHeadline}</p> : null}<ul className="mt-3 space-y-2 text-[11px] leading-4 text-muted">{[...(applicationGuide.resumePlan?.evidenceToLead ?? []), ...(applicationGuide.resumePlan?.bulletStrategy ?? []), ...(applicationGuide.cvImprovements ?? [])].slice(0, 6).map((item) => <li key={item} className="flex gap-2"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />{item}</li>)}</ul></article>
                        <article className="rounded-xl border border-border bg-[#fff8f1] p-5"><div className="flex items-center gap-2"><Mail className="h-4 w-4 text-accent" /><h3 className="text-sm font-bold text-foreground">Cover letter direction</h3></div><p className="mt-3 text-xs leading-5 text-[#1d1e1c]">{applicationGuide.coverLetterPlan?.openingAngle || applicationGuide.coverLetterStrategy?.[0]}</p>{applicationGuide.coverLetterPlan?.motivationAngle ? <p className="mt-3 rounded-lg bg-[#fff8f1] px-3 py-2 text-[10px] leading-4 text-muted"><span className="font-bold text-foreground">Motivation:</span> {applicationGuide.coverLetterPlan.motivationAngle}</p> : null}<ul className="mt-3 space-y-2 text-[11px] leading-4 text-muted">{[...(applicationGuide.coverLetterPlan?.proofPoints ?? []), ...(applicationGuide.coverLetterStrategy ?? [])].slice(0, 5).map((item) => <li key={item} className="flex gap-2"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />{item}</li>)}</ul></article>
                      </div>
                      {(applicationGuide.risks ?? []).length ? <div className="rounded-xl border border-accent/25 bg-accent/10 p-4"><h3 className="flex items-center gap-2 text-xs font-bold text-accent"><AlertTriangle className="h-4 w-4" /> Claims to avoid</h3><ul className="mt-2 grid gap-1 text-[10px] leading-4 text-accent sm:grid-cols-2">{applicationGuide.risks.map((risk) => <li key={risk}>• {risk}</li>)}</ul></div> : null}
                    </div>
                  ) : null}
                </div>
              ) : isAnalysisOutdated ? (
                <div className="m-5 rounded-xl border border-accent/25 bg-accent/10 px-5 py-8 text-center sm:px-8">
                  <AlertTriangle className="mx-auto h-6 w-6 text-accent" />
                  <p className="mt-3 text-sm font-bold text-accent">Analysis outdated</p>
                  <p className="mx-auto mt-2 max-w-2xl text-xs leading-5 text-accent">{isLegacyAnalysis ? "This application uses a legacy ai-match-v1 percentage without an application guide." : "This application does not have a complete application guide v3."} Refresh this application before generating a CV or cover letter.</p>
                  <Button type="button" disabled={isAnalysisRefreshing} onClick={() => onRefreshAnalysis(activeApplication.id)} className="mt-5 h-10 rounded-xl bg-accent px-4 text-xs font-bold text-[#ffffff] hover:bg-accent disabled:opacity-55">{isAnalysisRefreshing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}{isAnalysisRefreshing ? "Updating analysis…" : "Update this application"}</Button>
                </div>
              ) : <div className="m-5 rounded-xl border border-border bg-black/15 py-12 text-center"><Sparkles className="mx-auto h-5 w-5 text-muted" /><p className="mt-2 text-xs text-muted">Run AI Match for this vacancy to create the application plan.</p></div>}
            </section>
            </div>

            <div className={cn(activeWorkspaceStep !== "confirm" && "hidden")}>
            <section className={cn("workspace-card overflow-hidden", !confirmationsReady && "border-accent/25")}>
              <div className="flex items-start gap-3 border-b border-border px-5 py-5 sm:px-6">
                <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-xl", !confirmationsReady ? "bg-accent/10 text-accent" : "bg-success/10 text-success")}><MessageSquareText className="h-[18px] w-[18px]" /></span>
                <div className="min-w-0"><p className="text-[10px] font-black uppercase tracking-[0.14em] text-accent">02 · Improve your documents</p><h2 className="mt-1 text-lg font-bold text-foreground">Add your top three missing details</h2><p className="mt-1 text-xs leading-5 text-muted">These answers are used in both the tailored CV and cover letter. Choose yes, no, or partial and support positive answers with a concrete example.</p></div>
              </div>
              <div className="p-5 sm:p-6">
                {confirmationSyncMessage ? <div className={cn("mb-4 flex items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-[10px] leading-4", confirmationSyncStatus === "error" ? "border-accent/25 bg-accent/10 text-accent" : "border-accent/25 bg-accent/10 text-accent")}><span>{confirmationSyncMessage}</span>{confirmationSyncStatus === "error" ? <button type="button" onClick={retryApiRequests} className="inline-flex shrink-0 items-center gap-1 font-bold text-accent hover:text-foreground"><RefreshCw className="h-3 w-3" /> Retry</button> : null}</div> : null}
                {!hasCurrentAnalysis ? <div className="flex items-center gap-3 rounded-xl border border-accent/25 bg-accent/10 px-4 py-3 text-xs text-accent"><AlertTriangle className="h-5 w-5 shrink-0 text-accent" /><span>Update the analysis before confirming evidence. The legacy percentage does not contain the questions required for safe document generation.</span></div> : applicationClarificationQuestions.length ? <div className="grid gap-3">{applicationClarificationQuestions.map((question, index) => {
                  const confirmation = candidateConfirmations[question.id];
                  const answerLength = confirmation?.exampleText.trim().length ?? 0;
                  const isAnswered = Boolean(confirmation && (!question.blocking || isMeaningfulCandidateConfirmation(confirmation)));
                  const isOversized = answerLength > confirmationAnswerMaxChars;
                  const requiresExample = confirmation?.response === "yes" || confirmation?.response === "partial";
                  return <article key={question.id} className={cn("block rounded-xl border p-4 transition", isOversized ? "border-accent/25 bg-accent/10" : isAnswered ? "border-success/15 bg-success/[0.025]" : "border-border bg-black/15 focus-within:border-accent/25")}><span className="flex items-start gap-3"><span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[10px] font-black", isAnswered && !isOversized ? "border-success/25 bg-success/10 text-success" : "border-border text-muted")}>{isAnswered && !isOversized ? <Check className="h-3.5 w-3.5" /> : index + 1}</span><span className="min-w-0"><span className="flex flex-wrap items-center gap-2"><span className="text-xs font-bold leading-5 text-foreground">{question.question}</span>{question.blocking ? <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[8px] font-black uppercase text-accent">Required</span> : null}</span><span className="mt-1 block text-[10px] leading-4 text-[#615f5c]"><span className="font-bold text-[#1d1e1c]">Requirement:</span> {question.requirement}</span>{question.why ? <span className="mt-1 block text-[10px] leading-4 text-muted">Why it matters: {question.why}</span> : null}</span></span><div className="mt-3 grid grid-cols-3 gap-2">{(["yes", "no", "partial"] as CandidateConfirmationResponse[]).map((response) => <button key={response} type="button" onClick={() => updateCandidateConfirmation(question, { response })} className={cn("h-9 rounded-lg border text-[10px] font-black uppercase tracking-wide transition", confirmation?.response === response ? response === "no" ? "border-accent/25 bg-accent/10 text-accent" : response === "partial" ? "border-accent/25 bg-accent/10 text-accent" : "border-success/35 bg-success/10 text-success" : "border-border bg-[#fff8f1] text-muted hover:bg-[#fff3e8] hover:text-foreground")}>{response}</button>)}</div><textarea value={confirmation?.exampleText ?? ""} disabled={!confirmation} maxLength={confirmationAnswerMaxChars} onChange={(event) => updateCandidateConfirmation(question, { exampleText: event.target.value })} rows={2} placeholder={!confirmation ? "Choose yes, no, or partial first" : requiresExample ? "Add a true, concrete example" : "Optional context for this answer"} className="mt-3 w-full resize-y rounded-xl border border-border bg-[#ffffff] px-3 py-2.5 text-xs leading-5 text-foreground outline-none placeholder:text-muted/55 focus:border-accent/25 disabled:cursor-not-allowed disabled:opacity-45" /><span className="mt-1.5 flex items-center justify-between gap-3"><span className={cn("text-[9px]", question.blocking && requiresExample && !isMeaningfulCandidateConfirmation(confirmation) ? "font-bold text-accent" : "text-muted")}>{question.blocking && requiresExample && !isMeaningfulCandidateConfirmation(confirmation) ? "Add a specific example (at least two meaningful words)." : confirmationsDirty ? "Pending backend save" : confirmation?.updatedAt ? `Updated ${new Date(confirmation.updatedAt).toLocaleString("en-US", { hour12: false })}` : "Changes save automatically"}</span><span className={cn("text-[9px]", isOversized ? "font-bold text-accent" : "text-muted")}>{answerLength.toLocaleString()} / {confirmationAnswerMaxChars.toLocaleString()}</span></span></article>;
                })}</div> : <div className="flex items-center gap-3 rounded-xl border border-success/15 bg-success/[0.035] px-4 py-3 text-xs text-[#1d1e1c]"><CheckCircle2 className="h-5 w-5 shrink-0 text-success" /><span>No additional confirmations are required. Your verified profile is enough to continue.</span></div>}
              </div>
            </section>
            </div>

            <div className={cn(activeWorkspaceStep !== "create" && "hidden")}>
            <section className="overflow-hidden border-y border-border bg-[#ffffff]/45">
              <div className="flex flex-col gap-4 border-b border-border px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                <div><p className="text-[10px] font-black uppercase tracking-[0.14em] text-accent">03 · Create documents</p><h2 className="mt-1 text-lg font-bold text-foreground">Application package</h2><p className="mt-1 text-xs leading-5 text-muted">Prepare, generate and download both application documents from one workspace.</p></div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[9px] text-muted"><span>AI provider: <strong className="text-foreground">{aiConfiguration.providerName}</strong></span></div>
              </div>
              <div className="border-b border-border px-5 py-4 sm:px-6">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-[10px] font-black uppercase tracking-[0.12em] text-foreground">Document language</p>
                    <p className="mt-1 text-[10px] leading-4 text-muted">Applied to both the tailored CV and cover letter before generation.</p>
                  </div>
                  <label className="flex shrink-0 items-center gap-3">
                    <span className="text-[10px] font-bold text-muted">Language</span>
                    <select aria-label="Document language" value={languageMode} onChange={(event) => setLanguageMode(event.target.value as "auto" | "English" | "German")} className="h-9 min-w-40 border-0 border-b border-border bg-transparent px-0 text-[11px] font-bold text-foreground outline-none focus:border-accent">
                      <option value="auto">Auto · {vacancyLanguage || "English"}</option>
                      <option value="English">English</option>
                      <option value="German">German</option>
                    </select>
                  </label>
                </div>
              </div>
              <div className="p-5 sm:p-6">
                {documentError ? <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-accent/25 bg-accent/10 px-3 py-2.5 text-xs leading-5 text-accent"><span>{documentError}</span><button type="button" onClick={retryApiRequests} className="inline-flex shrink-0 items-center gap-1.5 font-bold text-accent hover:text-foreground"><RefreshCw className="h-3.5 w-3.5" /> Retry</button></div> : null}
                {resumeTailoringProgress ? <ResumeTailoringProgressPanel progress={resumeTailoringProgress} /> : null}
                {packProgress ? <div className={cn("mb-4 rounded-xl border p-3", packProgress.status === "failed" ? "border-accent/25 bg-accent/10" : packProgress.status === "partial" ? "border-accent/25 bg-accent/10" : "border-border bg-black/15")}><div className="grid gap-2 sm:grid-cols-4">{packStageDefinitions.map((stage, index) => { const currentIndex = packStageDefinitions.findIndex((candidate) => candidate.id === packProgress.stage); const stageStatus = index < currentIndex ? "completed" : index === currentIndex ? packProgress.status : "pending"; return <div key={stage.id} className={cn("rounded-lg border px-2.5 py-2", stageStatus === "completed" ? "border-success/20 bg-success/[0.05]" : stageStatus === "failed" ? "border-accent/25 bg-accent/10" : stageStatus === "partial" ? "border-accent/25 bg-accent/10" : stageStatus === "active" || stageStatus === "retrying" ? "border-accent/30 bg-accent/[0.07]" : "border-border bg-[#fff8f1]")}><div className="flex items-center gap-2">{stageStatus === "completed" ? <Check className="h-3.5 w-3.5 text-success" /> : stageStatus === "active" || stageStatus === "retrying" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin text-accent" /> : stageStatus === "failed" ? <AlertTriangle className="h-3.5 w-3.5 text-accent" /> : <CircleDot className="h-3.5 w-3.5 text-muted" />}<span className={cn("text-[9px] font-black uppercase tracking-wide", stageStatus === "completed" ? "text-success" : stageStatus === "failed" ? "text-accent" : stageStatus === "partial" ? "text-accent" : stageStatus === "active" || stageStatus === "retrying" ? "text-foreground" : "text-muted")}>{stage.label}</span></div></div>; })}</div><div className="mt-2 flex items-center justify-between gap-3 px-1 text-[9px]"><span className={cn(packProgress.status === "failed" ? "text-accent" : packProgress.status === "partial" ? "text-accent" : "text-muted")}>{packProgress.message}</span><span className="shrink-0 font-mono text-muted">{packProgress.attempt > 1 ? `attempt ${packProgress.attempt}/3 · ` : ""}{packProgress.jobId.slice(-8)}</span></div></div> : null}
                {masterResumeLoaded && !currentMasterResume ? <div className="mb-4 rounded-xl border border-accent/25 bg-accent/10 px-3 py-2.5 text-xs leading-5 text-accent">Confirm your Master Resume in My Profile before tailoring a vacancy.</div> : null}
                <div>
                  <DocumentCard sectionLabel="Resume document" documentType="tailored_resume" icon={FileText} label="Tailored CV" description="Create and download a tailored CV for this role." document={latestResume} isOutdated={isResumeOutdated} isGenerating={generationType === "tailored_resume"} restoringVersionKey={restoringVersionKey} loadingVersionHistoryId={loadingVersionHistoryId} deletingDocumentId={deletingDocumentId} onGenerate={() => requestAiGeneration("tailored_resume")} onRestore={(version) => latestResume && restoreDocumentVersion(latestResume, version)} onLoadMoreVersions={() => latestResume && void loadMoreDocumentVersions(latestResume)} onDelete={() => latestResume && void deleteGeneratedDocument(latestResume)} canGenerate={Boolean(!isGeneratingPack && documentsLoaded && currentMasterResume && resumeTemplates.length && applicationReview && confirmationsReady)} disabledLabel={isGeneratingPack ? "Pack job running…" : !documentsLoaded || !masterResumeLoaded ? "Loading…" : !currentMasterResume ? "Confirm Master Resume" : !resumeTemplates.length ? "Loading templates…" : !applicationReview ? analysisRequiredLabel : hasOversizedConfirmation ? "Shorten confirmation" : "Complete required answers"} sourceControl={<><p className="mt-3 text-[9px] text-muted">Master Resume · {currentMasterResume ? `v${currentMasterResume.version} confirmed` : "required"}</p><ResumeTemplatePicker compact apiBaseUrl={apiBaseUrl} templates={resumeTemplates} selectedId={selectedResumeTemplateId} onChange={selectResumeTemplate} notice={resumeTemplateNotice} /></>} generationControl={<ResumeGenerationModePicker selectedId={selectedResumeGenerationMode} onChange={selectResumeGenerationMode} disabled={Boolean(generationType || isGeneratingPack)} />} />
                  <CollapsibleDocumentPreview
                    title="Resume preview"
                    description="Open the exact generated PDF, ATS scan and document changes"
                    available={Boolean(latestResume)}
                  >
                    {latestResumeIsPdf ? (
                      <ResumePdfReview
                        apiBaseUrl={apiBaseUrl}
                        applicationId={activeApplication.id}
                        document={latestResume}
                        templates={resumeTemplates}
                        selectedTemplateId={selectedResumeTemplateId}
                        onDocumentReady={(renderedDocument) => {
                          setDocuments((current) => [
                            renderedDocument as GeneratedDocument,
                            ...current.filter((item) => item.id !== renderedDocument.id),
                          ]);
                        }}
                        onTemplateUnavailable={handleResumeTemplateUnavailable}
                      />
                    ) : latestResume ? (
                      <DocumentPdfPreview
                        apiBaseUrl={apiBaseUrl}
                        document={latestResume}
                        label="Resume"
                      />
                    ) : null}
                  </CollapsibleDocumentPreview>
                  <DocumentCard
                    sectionLabel="Cover letter document"
                    documentType="cover_letter"
                    icon={Mail}
                    label="Cover letter"
                    description="A restrained Swiss-style motivation letter: why this role, relevant proof, and the value you can deliver."
                    document={latestCoverLetter}
                    isOutdated={isCoverLetterOutdated}
                    isGenerating={generationType === "cover_letter"}
                    restoringVersionKey={restoringVersionKey}
                    loadingVersionHistoryId={loadingVersionHistoryId}
                    deletingDocumentId={deletingDocumentId}
                    onGenerate={() => requestAiGeneration("cover_letter")}
                    onRestore={(version) => latestCoverLetter && restoreDocumentVersion(latestCoverLetter, version)}
                    onLoadMoreVersions={() => latestCoverLetter && void loadMoreDocumentVersions(latestCoverLetter)}
                    onDelete={() => latestCoverLetter && void deleteGeneratedDocument(latestCoverLetter)}
                    canGenerate={Boolean(!isGeneratingPack && documentsLoaded && coverLetterTemplate && coverLetterNamesComplete && applicationReview && confirmationsReady)}
                    disabledLabel={isGeneratingPack ? "Pack job running…" : !documentsLoaded ? documentError ? "Retry loading history" : "Loading history…" : !coverLetterTemplate ? "Loading template…" : !coverLetterNamesComplete ? "Complete contact names" : !applicationReview ? analysisRequiredLabel : hasOversizedConfirmation ? "Shorten confirmation" : "Complete required answers"}
                    sourceControl={(
                      <CoverLetterTemplateCard
                        apiBaseUrl={apiBaseUrl}
                        template={coverLetterTemplate}
                      />
                    )}
                    generationControl={(
                      <div className="mt-4 grid gap-5 border-t border-border pt-4">
                        <label className="block">
                          <span className="text-[10px] font-bold text-[#1d1e1c]">Recruiter name <span className="font-normal text-muted">(optional)</span></span>
                          <span className="mt-1 block text-[9px] leading-4 text-muted">Used in the greeting. Leave empty to address the company&apos;s hiring team.</span>
                          <input
                            aria-label="Recruiter name"
                            value={coverLetterRecipientName}
                            maxLength={160}
                            onChange={(event) => {
                              const name = event.target.value;
                              updateCandidateConfirmation(coverLetterRecipientQuestion, {
                                response: name.trim() ? "yes" : "no",
                                exampleText: name,
                              });
                            }}
                            placeholder="First name and last name"
                            className={cn("mt-2 h-10 w-full border-0 border-b bg-transparent px-0 text-xs text-foreground outline-none placeholder:text-muted/55", coverLetterRecipientNameComplete ? "border-border focus:border-accent" : "border-accent/25 focus:border-accent/25")}
                          />
                          {!coverLetterRecipientNameComplete ? <span className="mt-1.5 block text-[9px] font-bold text-accent">Enter first and last name or leave the field empty.</span> : null}
                        </label>
                        <label className="block">
                          <span className="text-[10px] font-bold text-[#1d1e1c]">Know someone at the company? <span className="font-normal text-muted">(optional)</span></span>
                          <span className="mt-1 block text-[9px] leading-4 text-muted">Enter their full name. The letter will open with this connection and how it strengthened your positive impression of the company.</span>
                          <input
                            aria-label="Company contact name"
                            value={coverLetterCompanyContactName}
                            maxLength={160}
                            onChange={(event) => {
                              const name = event.target.value;
                              updateCandidateConfirmation(coverLetterCompanyContactQuestion, {
                                response: name.trim() ? "yes" : "no",
                                exampleText: name,
                              });
                            }}
                            placeholder="First name and last name"
                            className={cn("mt-2 h-10 w-full border-0 border-b bg-transparent px-0 text-xs text-foreground outline-none placeholder:text-muted/55", coverLetterCompanyContactNameComplete ? "border-border focus:border-accent" : "border-accent/25 focus:border-accent/25")}
                          />
                          {!coverLetterCompanyContactNameComplete ? <span className="mt-1.5 block text-[9px] font-bold text-accent">Enter first and last name or leave the field empty.</span> : null}
                        </label>
                      </div>
                    )}
                  />
                  <CollapsibleDocumentPreview
                    title="Cover letter preview"
                    description="Open the exact generated cover letter PDF"
                    available={Boolean(latestCoverLetter)}
                  >
                    {latestCoverLetter ? (
                      <DocumentPdfPreview
                        apiBaseUrl={apiBaseUrl}
                        document={latestCoverLetter}
                        label="Cover letter"
                      />
                    ) : null}
                  </CollapsibleDocumentPreview>
                </div>
                <div className="flex flex-col gap-4 border-t border-border py-6 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-[11px] font-bold text-foreground">
                      {resumeReady && coverLetterReady ? "2 documents ready" : "Create the complete application set"}
                    </p>
                    <p className="mt-1 text-[9px] leading-4 text-muted">
                      DOCX and PDF downloads stay with each document above.
                    </p>
                  </div>
                  <Button
                    type="button"
                    aria-label="Generate application pack"
                    onClick={() => requestAiGeneration("pack")}
                    disabled={isGeneratingPack || Boolean(generationType) || !documentsLoaded || !currentMasterResume || !coverLetterTemplate || !coverLetterNamesComplete || !applicationReview || !confirmationsReady}
                    className="h-10 shrink-0 rounded-lg bg-accent px-4 text-[11px] font-bold text-foreground hover:bg-[#e95300] disabled:opacity-40"
                  >
                    {isGeneratingPack ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : resumeReady && coverLetterReady ? <RefreshCw className="h-3.5 w-3.5" /> : null}
                    {isGeneratingPack ? packStageDefinitions.find((stage) => stage.id === packProgress?.stage)?.label ?? "Generating…" : resumeReady && coverLetterReady ? "Regenerate both" : "Create both documents"}
                  </Button>
                </div>
                <details open className="group border-t border-border py-5">
                  <summary className="flex cursor-pointer list-none flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <p className="text-[10px] font-black uppercase tracking-[0.12em] text-accent">Application AI chat</p>
                      <h3 className="mt-1 text-sm font-bold text-foreground">Ask questions or improve either document</h3>
                      <p className="mt-1 text-[10px] leading-4 text-muted">Choose a mode, then ask about the application or request a CV or cover-letter revision.</p>
                    </div>
                    <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted transition group-open:rotate-90" />
                  </summary>
                  <div className="pt-4">
                  <div role="group" aria-label="AI chat mode" className="mt-4 grid gap-2 sm:grid-cols-3">
                    {([
                      ["question", "Ask a question"],
                      ["tailored_resume", "Revise CV"],
                      ["cover_letter", "Revise cover letter"],
                    ] as Array<[DocumentChatTarget, string]>).map(([target, targetLabel]) => (
                      <button
                        key={target}
                        type="button"
                        aria-pressed={documentChatTarget === target}
                        onClick={() => setDocumentChatTarget(target)}
                        className={cn(
                          "h-10 rounded-xl border text-[10px] font-black transition",
                          documentChatTarget === target
                            ? "border-accent/45 bg-accent/12 text-foreground"
                            : "border-border bg-black/15 text-muted hover:bg-[#fff3e8] hover:text-foreground",
                        )}
                      >
                        {targetLabel}
                      </button>
                    ))}
                  </div>
                  <div className="mt-4 max-h-56 space-y-2 overflow-y-auto rounded-xl border border-border bg-black/20 p-3">
                    {documentChatMessages.length ? documentChatMessages.map((message) => <div key={message.id} className={cn("max-w-[88%] rounded-xl px-3 py-2 text-[11px] leading-5", message.role === "user" ? "ml-auto bg-accent/15 text-foreground" : "border border-border bg-[#fff8f1] text-[#1d1e1c]")}>{message.text}</div>) : <p className="py-3 text-center text-[10px] leading-5 text-muted">Ask why the role fits, request stronger CV emphasis, or make the cover-letter opening less generic.</p>}
                    {isDocumentChatResponding ? <div className="flex max-w-[88%] items-center gap-2 rounded-xl border border-border bg-[#fff8f1] px-3 py-2 text-[11px] text-muted"><LoaderCircle className="h-3.5 w-3.5 animate-spin text-accent" /> Thinking…</div> : null}
                  </div>
                  <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
                    <label className="min-w-0 flex-1">
                      <span className="sr-only">AI chat message</span>
                      <textarea
                        aria-label="AI chat message"
                        value={documentChatInput}
                        onChange={(event) => setDocumentChatInput(event.target.value)}
                        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); applyDocumentChatInstruction(); } }}
                        rows={2}
                        maxLength={2_000}
                        placeholder={documentChatPlaceholder}
                        className="w-full resize-y rounded-xl border border-border bg-[#ffffff] px-3 py-2.5 text-xs leading-5 text-foreground outline-none placeholder:text-muted/55 focus:border-accent/40"
                      />
                    </label>
                    <Button type="button" onClick={applyDocumentChatInstruction} disabled={!documentChatInput.trim() || Boolean(generationType) || isGeneratingPack || isDocumentChatResponding || !documentChatCanSubmit} className="h-11 shrink-0 rounded-xl bg-accent px-4 text-xs font-bold text-foreground disabled:opacity-40">{isDocumentChatResponding || generationType === documentChatTarget ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}{documentChatTarget === "question" ? "Send" : "Apply revision"}</Button>
                  </div>
                  {!documentChatTargetReady ? <p className="mt-2 text-[9px] font-bold text-accent">{documentChatUnavailableMessage}</p> : null}
                  </div>
                </details>
              </div>
            </section>
            </div>

            <section className={cn("workspace-card overflow-hidden", activeWorkspaceStep !== "final" && "hidden")}>
              <div className="border-b border-border px-5 py-5 sm:px-6">
                <p className="text-[10px] font-black uppercase tracking-[0.14em] text-accent">04 · Final review</p>
                <h2 className="mt-1 text-lg font-bold text-foreground">Review, download and apply</h2>
                <p className="mt-1 text-xs leading-5 text-muted">Open both documents, check the final content and continue to the employer website.</p>
              </div>
              <div className="p-5 sm:p-6">
                <div className="grid gap-3 sm:grid-cols-2">
                  {[
                    { label: "Tailored CV", document: latestResume, ready: resumeReady, icon: FileText },
                    { label: "Cover letter", document: latestCoverLetter, ready: coverLetterReady, icon: Mail },
                  ].map((item) => {
                    const ItemIcon = item.icon;
                    const itemDocxDownload = item.label === "Tailored CV" && item.document
                      ? resumeDocxDownload(item.document)
                      : null;
                    const itemPdfDownload = item.label === "Cover letter" && item.document
                      ? coverLetterPdfDownload(item.document)
                      : null;
                    const itemCurrentArtifact = item.document?.versions.find(
                      (version) => (
                        version.version === item.document?.currentVersion
                      ),
                    )?.artifact;
                    const itemIsImaginator = Boolean(
                      item.label === "Tailored CV"
                      && itemCurrentArtifact
                      && resumeArtifactGenerationMode(itemCurrentArtifact)
                        === "imaginator",
                    );
                    const itemDownloadWarnings = item.document
                      ? [
                          ...getGeneratedDocumentReadiness(
                            item.document,
                            item.label === "Tailored CV"
                              ? isResumeOutdated
                              : isCoverLetterOutdated,
                          ).warnings,
                          ...(itemIsImaginator
                            ? [
                                "the Imaginator draft contains AI-invented claims",
                              ]
                            : []),
                        ]
                      : [];
                    return (
                      <article key={item.label} className="rounded-2xl border border-border bg-black/15 p-4">
                        <div className="flex items-start gap-3">
                          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border bg-[#fff8f1] text-accent"><ItemIcon className="h-4 w-4" /></span>
                          <div className="min-w-0 flex-1"><p className="text-sm font-bold text-foreground">{item.label}</p><p className={cn("mt-1 text-[10px] font-bold", item.ready ? "text-success" : "text-accent")}>{item.ready ? "Ready for final review" : "Needs attention before applying"}</p></div>
                        </div>
                        <div className="mt-4 flex gap-2">
                          <Button type="button" variant="ghost" onClick={() => setActiveWorkspaceStep("create")} className="h-9 flex-1 rounded-xl border border-border text-[10px] font-bold text-[#1d1e1c] hover:bg-[#fff3e8]">{item.document ? "Review & edit" : "Prepare document"}</Button>
                          {itemPdfDownload ? <a href={itemPdfDownload.href} download={itemPdfDownload.fileName} onClick={(event) => confirmDocumentDownload(event, itemDownloadWarnings)} className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border px-3 text-[10px] font-bold text-foreground transition hover:bg-[#fff3e8]"><Download className="h-3.5 w-3.5" /> PDF</a> : null}
                          {item.document ? <a href={`${apiBaseUrl}/documents/${encodeURIComponent(item.document.id)}/download`} download={documentFileName(item.document)} onClick={(event) => confirmDocumentDownload(event, itemDownloadWarnings)} className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border px-3 text-[10px] font-bold text-foreground transition hover:bg-[#fff3e8]"><Download className="h-3.5 w-3.5" /> {documentArtifactLabel(item.document)}</a> : null}
                          {itemDocxDownload ? <a href={itemDocxDownload.href} download={itemDocxDownload.fileName} onClick={(event) => confirmDocumentDownload(event, itemDownloadWarnings)} className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border px-3 text-[10px] font-bold text-foreground transition hover:bg-[#fff3e8]"><Download className="h-3.5 w-3.5" /> DOCX</a> : null}
                        </div>
                      </article>
                    );
                  })}
                </div>
                <div className="mt-5 grid gap-3 rounded-2xl border border-border bg-[#fff8f1] p-4 sm:grid-cols-3">
                  {[{ icon: Sparkles, label: "Generate", text: "Create both tailored documents." }, { icon: FileCheck2, label: "Review", text: "Check content, layout and validation." }, { icon: Download, label: "Download & apply", text: "Download the approved files and submit." }].map((item) => { const ItemIcon = item.icon; return <div key={item.label} className="flex gap-3"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-border text-muted"><ItemIcon className="h-4 w-4" /></span><div><p className="text-xs font-bold text-foreground">{item.label}</p><p className="mt-1 text-[10px] leading-4 text-muted">{item.text}</p></div></div>; })}
                </div>
                <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-end">
                  <Button type="button" variant="ghost" disabled={!jobUrl} onClick={() => jobUrl && window.open(jobUrl, "_blank", "noopener,noreferrer")} className="h-11 rounded-xl border border-border px-4 text-xs font-bold text-foreground"><ExternalLink className="h-4 w-4" /> Open vacancy</Button>
                  {application.status === "draft" ? <Button onClick={() => onMarkApplied(application.id)} className="h-11 rounded-xl bg-success px-5 text-xs font-black text-white hover:bg-[#e95300]"><Check className="h-4 w-4" /> Mark as applied</Button> : <div className="flex h-11 items-center justify-center gap-2 rounded-xl border border-success/25 bg-success/10 px-5 text-xs font-bold text-success"><Check className="h-4 w-4" /> Application tracked</div>}
                </div>
              </div>
            </section>
          </main>

          <aside className="space-y-4 xl:sticky xl:top-4">
            <section className="overflow-hidden border-y border-border bg-[#ffffff]/35">
              <div className="border-b border-border p-5"><div className="flex items-end justify-between"><div><p className="text-[10px] font-black uppercase tracking-[0.13em] text-accent">Readiness</p><h2 className="mt-1 text-base font-bold text-foreground">Before you apply</h2></div><span className="text-2xl font-black text-foreground">{progress}<span className="text-sm text-muted">%</span></span></div><div className="mt-4 h-1.5 overflow-hidden rounded-full bg-[#fff8f1]"><div className="h-full rounded-full bg-gradient-to-r from-accent to-[#e95300] transition-all" style={{ width: `${progress}%` }} /></div></div>
              <div className="px-4 pb-4"><div>{checklist.map((item) => <div key={item.label} className="flex items-center gap-2.5 border-b border-border px-2 py-3 last:border-b-0"><span className={cn("grid h-5 w-5 place-items-center rounded-full border", item.ready ? "border-success/25 bg-success/10 text-success" : "border-border text-[#615f5c]")}>{item.ready ? <Check className="h-3 w-3" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}</span><span className={cn("text-[11px] font-semibold", item.ready ? "text-[#1d1e1c]" : "text-muted")}>{item.label}</span><span className="ml-auto text-[8px] font-black uppercase tracking-wide text-[#615f5c]">{item.ready ? "Ready" : "Missing"}</span></div>)}</div>
                {activeWorkspaceStep === "create" ? (
                  <p className="mt-3 px-2 text-[9px] leading-4 text-muted">Create and download actions are available beside each document.</p>
                ) : activeWorkspaceStep === "final" ? (
                  <Button type="button" onClick={() => setActiveWorkspaceStep("create")} className="mt-4 h-11 w-full rounded-xl bg-accent text-xs font-bold text-foreground"><FileText className="h-4 w-4" /> Back to documents</Button>
                ) : (
                  <Button type="button" onClick={() => setActiveWorkspaceStep(activeWorkspaceStep === "review" ? "confirm" : "create")} className="mt-4 h-11 w-full rounded-xl bg-accent text-xs font-bold text-foreground">Continue <ChevronRight className="h-4 w-4" /></Button>
                )}
                <div className={cn("mt-3 flex items-center justify-between rounded-lg px-2 py-2 text-[9px]", apiHealth === "unavailable" ? "bg-accent/10 text-accent" : "text-muted")} role="status" aria-live="polite"><span className="inline-flex items-center gap-1.5"><span className={cn("h-1.5 w-1.5 rounded-full", apiHealth === "available" ? "bg-success" : apiHealth === "unavailable" ? "bg-accent" : "animate-pulse bg-muted")} />{apiHealth === "available" ? "Services available" : apiHealth === "unavailable" ? "Services unavailable" : "Checking services…"}</span>{apiHealth === "unavailable" ? <button type="button" onClick={retryApiRequests} className="inline-flex items-center gap-1 font-bold hover:text-foreground"><RefreshCw className="h-3 w-3" /> Retry</button> : null}</div>
              </div>
            </section>

            <section className={cn("workspace-card overflow-hidden", activeWorkspaceStep === "create" && "hidden")}>
              <div className="flex items-center gap-3 border-b border-border p-4"><span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/12 text-accent"><Bot className="h-4 w-4" /></span><div><h2 className="text-sm font-bold text-foreground">Application coach</h2><p className="mt-0.5 text-[10px] text-muted">Ask about this vacancy</p></div></div>
              <div className="p-4"><div className="grid gap-2">{["What should I emphasize?", "What are the biggest risks?", "Help with application questions"].map((prompt) => <button key={prompt} type="button" disabled={isLoadingAdvice} onClick={() => requestAdvice(prompt)} className={cn("rounded-xl border px-3 py-2.5 text-left text-[11px] font-semibold leading-4 transition", advicePrompt === prompt ? "border-accent/35 bg-accent/10 text-foreground" : "border-border bg-[#fff8f1] text-[#4a4a47] hover:border-accent/25 hover:bg-accent/[0.05]")}>{prompt}</button>)}</div>
                {(isLoadingAdvice || advice) ? <div className="job-scroll mt-3 max-h-[300px] overflow-y-auto rounded-xl border border-border bg-black/20 p-3">{isLoadingAdvice ? <div className="flex items-center gap-2 text-xs text-muted"><LoaderCircle className="h-4 w-4 animate-spin text-accent" /> Reviewing…</div> : <p className="whitespace-pre-wrap text-[11px] leading-5 text-[#1d1e1c]">{advice}</p>}</div> : null}
                <Button variant="ghost" onClick={() => onOpenAssistant("Review this application and help me finish it.", application.id)} className="mt-3 h-9 w-full rounded-xl border border-border bg-transparent text-[11px] text-[#1d1e1c] hover:bg-[#fff3e8]">Open full Assistant <ChevronRight className="h-4 w-4" /></Button>
              </div>
            </section>
          </aside>
        </div>
      </div>
    </section>
    </>
  );
}

function ResumeGenerationModePicker({
  selectedId,
  onChange,
  disabled = false,
}: {
  selectedId: ResumeGenerationMode;
  onChange: (mode: ResumeGenerationMode) => void;
  disabled?: boolean;
}) {
  const selectedMode =
    resumeGenerationModes.find((mode) => mode.id === selectedId)
    ?? resumeGenerationModes[0];
  const [isInfoOpen, setIsInfoOpen] = useState(false);

  return (
    <section
      aria-labelledby="resume-generation-mode-title"
      className="mt-4 border-t border-border pt-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p
          id="resume-generation-mode-title"
          className="text-[9px] font-black uppercase tracking-[0.1em] text-muted"
        >
          CV generation mode
        </p>
        <div className="flex items-center gap-2">
          <label className="shrink-0">
            <span className="sr-only">Mode</span>
            <select
              aria-label="CV generation mode"
              value={selectedId}
              disabled={disabled}
              onChange={(event) => onChange(event.target.value as ResumeGenerationMode)}
              className="h-9 min-w-48 rounded-lg border border-border bg-[#ffffff] px-3 text-[10px] font-bold text-foreground outline-none focus:border-accent/60 disabled:cursor-not-allowed disabled:opacity-45"
            >
              {resumeGenerationModes.map((mode) => (
                <option key={mode.id} value={mode.id}>
                  {mode.name}
                </option>
              ))}
            </select>
          </label>
          <div className="relative">
            <button
              type="button"
              aria-label="About selected CV generation mode"
              aria-expanded={isInfoOpen}
              aria-controls="resume-generation-mode-info"
              onClick={() => setIsInfoOpen((current) => !current)}
              className="grid h-9 w-9 place-items-center rounded-lg border border-border text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
            >
              <Info className="h-4 w-4" />
            </button>
            {isInfoOpen ? <div id="resume-generation-mode-info" className="absolute right-0 top-11 z-30 w-72 rounded-xl border border-border bg-[#ffffff] p-4 shadow-[0_18px_50px_rgba(0,0,0,0.5)]">
              <p className="text-[10px] font-bold text-foreground">{selectedMode.name}</p>
              <p className="mt-2 text-[9px] leading-4 text-[#4a4a47]">
                {selectedMode.description}
              </p>
              <p className="mt-3 border-t border-border pt-3 text-[8px] font-black uppercase tracking-[0.1em] text-muted">
                {selectedMode.stages}
              </p>
            </div> : null}
          </div>
        </div>
      </div>
      {selectedId === "imaginator" ? (
        <div
          role="alert"
          className="mt-3 flex items-start gap-2 rounded-lg border border-accent/25 bg-accent/10 px-3 py-2.5 text-accent"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <p className="text-[9px] leading-4">
            Imaginator may invent experience, achievements, skills, and
            qualifications. Employer names, education, and candidate identity
            remain locked. Review every generated claim before use.
          </p>
        </div>
      ) : null}
    </section>
  );
}

function DocumentCard({
  sectionLabel,
  documentType,
  icon: Icon,
  label,
  description,
  document,
  isOutdated,
  isGenerating,
  restoringVersionKey,
  loadingVersionHistoryId,
  deletingDocumentId,
  onGenerate,
  onRestore,
  onLoadMoreVersions,
  onDelete,
  canGenerate,
  disabledLabel,
  sourceControl,
  generationControl,
}: {
  sectionLabel: string;
  documentType: GeneratedDocument["type"];
  icon: typeof FileText;
  label: string;
  description: string;
  document: GeneratedDocument | undefined;
  isOutdated: boolean;
  isGenerating: boolean;
  restoringVersionKey: string;
  loadingVersionHistoryId: string;
  deletingDocumentId: string;
  onGenerate: () => void;
  onRestore: (version: number) => void;
  onLoadMoreVersions: () => void;
  onDelete: () => void;
  canGenerate: boolean;
  disabledLabel: string;
  sourceControl?: React.ReactNode;
  generationControl?: React.ReactNode;
}) {
  const currentVersion = document?.versions.find((version) => version.version === document.currentVersion);
  const readiness = getGeneratedDocumentReadiness(document, isOutdated);
  const isResume = documentType === "tailored_resume";
  const isImaginatorResume = Boolean(
    isResume
    && currentVersion?.artifact
    && resumeArtifactGenerationMode(currentVersion.artifact) === "imaginator",
  );
  const currentDownloadWarnings = isImaginatorResume
    ? [
        ...readiness.warnings,
        "the Imaginator draft contains AI-invented claims",
      ]
    : readiness.warnings;
  const docxDownload = document && isResume
    ? resumeDocxDownload(document)
    : null;
  const pdfDownload = document && !isResume
    ? coverLetterPdfDownload(document)
    : null;
  const isRestoringDocument = Boolean(document && restoringVersionKey.startsWith(`${document.id}:`));
  return (
    <article className="border-t border-border py-7 first:border-t-0">
      <div className="grid gap-6 lg:grid-cols-[minmax(150px,0.72fr)_minmax(250px,1.2fr)_minmax(250px,0.95fr)] lg:gap-8">
      <div className="min-w-0">
        <p className="text-[9px] font-black uppercase tracking-[0.16em] text-accent">{isResume ? "01" : "02"} · {sectionLabel}</p>
        <Icon className="mt-5 h-5 w-5 text-[#1d1e1c]" />
        <h3 className="mt-3 text-sm font-bold text-foreground">{label}</h3>
        <p className="mt-1 text-[10px] leading-4 text-muted">{description}</p>
      </div>
      <div className="min-w-0">
      {sourceControl}
      {generationControl}
      </div>
      <div className="min-w-0 lg:border-l border-border lg:pl-8">
      <p className={cn("flex items-center gap-2 text-[10px] font-bold", document ? readiness.ready ? "text-success" : "text-accent" : "text-muted")}>
        <span className={cn("h-1.5 w-1.5 rounded-full", document ? readiness.ready ? "bg-success" : "bg-accent" : "bg-[#615f5c]")} />
        {isGenerating
          ? "Generating…"
          : document
            ? `${isImaginatorResume ? "Idealized draft" : readiness.ready ? "Ready" : readiness.label} · v${document.currentVersion}`
            : `Not created · ${canGenerate ? "Ready to generate" : disabledLabel}`}
      </p>
      {isImaginatorResume ? (
        <p className="mt-1 text-[9px] leading-4 text-accent">
          Contains AI-invented claims · review before use
        </p>
      ) : null}
      {currentVersion ? <p className="mt-1 text-[9px] text-muted">Generated {formatVersionTimestamp(currentVersion.createdAt)}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        {pdfDownload ? <a href={pdfDownload.href} download={pdfDownload.fileName} onClick={(event) => confirmDocumentDownload(event, currentDownloadWarnings)} className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-border px-3 text-[11px] font-bold text-[#1d1e1c] transition hover:bg-[#fff3e8]"><Download className="h-3.5 w-3.5" /> PDF</a> : null}
        {document ? <a href={`${apiBaseUrl}/documents/${encodeURIComponent(document.id)}/download`} download={documentFileName(document)} onClick={(event) => confirmDocumentDownload(event, currentDownloadWarnings)} className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-border px-3 text-[11px] font-bold text-[#1d1e1c] transition hover:bg-[#fff3e8]"><Download className="h-3.5 w-3.5" /> {documentArtifactLabel(document)}</a> : null}
        {docxDownload ? <a href={docxDownload.href} download={docxDownload.fileName} onClick={(event) => confirmDocumentDownload(event, currentDownloadWarnings)} className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-border px-3 text-[11px] font-bold text-[#1d1e1c] transition hover:bg-[#fff3e8]"><Download className="h-3.5 w-3.5" /> DOCX</a> : null}
        <Button type="button" aria-label={isGenerating ? "Generating…" : !canGenerate ? disabledLabel : document ? "Regenerate" : `Generate ${label}`} variant={document ? "ghost" : "default"} disabled={isGenerating || isRestoringDocument || !canGenerate} onClick={onGenerate} className={cn("h-10 px-3 text-[11px] font-bold disabled:opacity-40", document ? "rounded-none border-0 bg-transparent text-muted hover:bg-transparent hover:text-foreground" : "rounded-lg bg-accent text-foreground hover:bg-[#e95300]")}>{isGenerating ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : document ? <RefreshCw className="h-3.5 w-3.5" /> : null}{isGenerating ? "Generating…" : document ? "Regenerate" : `Create ${isResume ? "CV" : "letter"}`}</Button>
        {document && !isResume ? <Button type="button" variant="ghost" aria-label={`Delete ${label}`} disabled={deletingDocumentId === document.id || isGenerating} onClick={onDelete} className="h-10 rounded-xl border border-accent/25 px-3 text-accent hover:bg-accent/10"><Trash2 className="h-3.5 w-3.5" /></Button> : null}
      </div>
      {document ? <p className="mt-2 text-[9px] leading-4 text-muted">Download the current {isResume ? "resume" : "cover letter"} as PDF or editable DOCX.</p> : null}
      {document ? (
        <details className="mt-3 rounded-xl border border-border bg-[#fff8f1]">
          <summary className="cursor-pointer px-3 py-2.5 text-[10px] font-bold text-[#4a4a47] marker:text-muted">
            Version history · {document.versionsTotal ?? document.versions.length}
          </summary>
          <div className="border-t border-border px-3 py-2">
            {[...document.versions].sort((left, right) => right.version - left.version).map((version) => {
              const isCurrent = version.version === document.currentVersion;
              const restoreKey = `${document.id}:${version.version}`;
              const isRestoring = restoringVersionKey === restoreKey;
              const downloadWarnings = getDocumentVersionDownloadWarnings(version, isCurrent && isOutdated);
              if (
                isResume
                && version.artifact
                && resumeArtifactGenerationMode(version.artifact) === "imaginator"
              ) {
                downloadWarnings.push(
                  "the Imaginator draft contains AI-invented claims",
                );
              }
              const versionPdfDownload = !isResume
                ? coverLetterPdfDownload(document, version.version)
                : null;
              return (
                <div key={version.id} className="flex items-center gap-2 border-b border-border py-2 last:border-0">
                  <div className="min-w-0 flex-1">
                    <p className="text-[10px] font-bold text-foreground">v{version.version}{isCurrent ? <span className="ml-1.5 text-[8px] uppercase tracking-wide text-success">Current</span> : null}</p>
                    <p className="mt-0.5 text-[9px] text-muted">{formatVersionTimestamp(version.createdAt)}</p>
                  </div>
                  {versionPdfDownload ? <a href={versionPdfDownload.href} download={versionPdfDownload.fileName} onClick={(event) => confirmDocumentDownload(event, downloadWarnings)} className="inline-flex h-7 items-center gap-1 rounded-md border border-border px-2 text-[9px] font-bold text-[#1d1e1c] hover:bg-[#fff3e8]"><Download className="h-3 w-3" /> PDF</a> : null}
                  <a href={`${apiBaseUrl}/documents/${encodeURIComponent(document.id)}/download?version=${version.version}`} download={documentFileName(document, version.version)} onClick={(event) => confirmDocumentDownload(event, downloadWarnings)} className="inline-flex h-7 items-center gap-1 rounded-md border border-border px-2 text-[9px] font-bold text-[#1d1e1c] hover:bg-[#fff3e8]"><Download className="h-3 w-3" /> {documentArtifactLabel(document, version.version)}</a>
                  {!isCurrent && !isResume ? <button type="button" disabled={Boolean(restoringVersionKey) || isGenerating} onClick={() => onRestore(version.version)} className="inline-flex h-7 items-center gap-1 rounded-md border border-border px-2 text-[9px] font-bold text-[#1d1e1c] transition hover:border-accent/30 hover:text-foreground disabled:opacity-40">{isRestoring ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} Restore</button> : null}
                </div>
              );
            })}
            {(document.versionsHasMore ?? document.versions.length < (document.versionsTotal ?? document.versions.length)) ? <Button type="button" variant="ghost" disabled={loadingVersionHistoryId === document.id} onClick={onLoadMoreVersions} className="mt-2 h-8 w-full rounded-lg border border-border text-[9px] font-bold text-muted hover:text-foreground">{loadingVersionHistoryId === document.id ? <LoaderCircle className="h-3 w-3 animate-spin" /> : null} Load older versions</Button> : null}
          </div>
        </details>
      ) : null}
      </div>
      </div>
    </article>
  );
}
