"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  Bot,
  BriefcaseBusiness,
  Check,
  ChevronDown,
  Copy,
  Download,
  FileText,
  History,
  Mail,
  MessageSquarePlus,
  Paperclip,
  Pencil,
  RefreshCw,
  Save,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  Target,
  Trash2,
  UserRound,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { getAiSourceLabel, type AiBackend, type AiSource } from "@/lib/ai-source";
import { cn } from "@/lib/utils";

export type AssistantLaunch = {
  id: string;
  prompt: string;
  contextKind: "profile" | "job" | "application";
  contextId?: string;
  autoSubmit?: boolean;
};

type AssistantProfile = {
  name: string;
  current_role: string;
  desired_role: string;
  location: string;
  headline: string;
  skills: string;
  experience: string;
  education: string;
  resume_file_name: string;
};

type AssistantJob = {
  id: string;
  title: string;
  company: string;
  location: string;
  type?: string;
  match: number;
  overview: string;
  responsibilities?: string[];
  requirements: string[];
  skills: string[];
  aiMatch?: {
    reasons: string[];
    gaps: string[];
  };
};

type AssistantApplication = {
  id: string;
  status: string;
  notes: string;
  nextStep: string;
  job: AssistantJob;
};

type AssistantContextKind = AssistantLaunch["contextKind"];
type AssistantConnectionStatus = "idle" | "connecting" | "connected" | "reconnecting" | "disconnected";

type AiPrivacySettings = {
  providerName: string;
  currentBackend: AiBackend;
  consentBackend: AiBackend | null;
  currentConsentVersion: string;
  hasCurrentConsent: boolean;
  retentionDays: number;
};

type AssistantSseEvent = {
  event: string;
  data: Record<string, unknown>;
};

type AssistantMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  source?: AiSource;
  status?: "generating" | "complete" | "stopped" | "error";
  actions?: AssistantActionPreview[];
};

type AssistantActionFieldPreview = {
  label: string;
  before: string;
  after: string;
};

type AssistantActionPreview = {
  id: string;
  type: "add_application_note" | "update_application_next_step" | "create_interview_event" | "save_document" | "update_profile_field";
  title: string;
  description: string;
  contextKind: AssistantContextKind;
  contextId: string;
  fields: AssistantActionFieldPreview[];
  payload: Record<string, unknown>;
  status: "preview" | "applying" | "applied" | "error";
  resultMessage: string;
};

export type AssistantAppliedAction = {
  actionId: string;
  type: AssistantActionPreview["type"];
  status: "applied";
  message: string;
  resourceKind: "application" | "event" | "document" | "profile";
  resource: Record<string, unknown>;
};

type AssistantThread = {
  id: string;
  title: string;
  contextKind: AssistantContextKind;
  contextId: string;
  providerSessionId?: string | null;
  archived: boolean;
  createdAt: string;
  updatedAt: string;
  messages: AssistantMessage[];
};

type AssistantDocumentVersion = {
  id: string;
  version: number;
  content: string;
  createdAt: string;
  artifact?: {
    fileName: string;
    contentType: string;
  } | null;
};

type AssistantDocument = {
  id: string;
  type: "cover_letter" | "tailored_resume";
  title: string;
  jobId: string | null;
  applicationIds: string[];
  currentVersion: number;
  createdAt: string;
  updatedAt: string;
  versions: AssistantDocumentVersion[];
};

type AssistantDocumentDraft = {
  id: string;
  type: "cover_letter";
  title: string;
  content: string;
  jobId: string;
  applicationId: string;
};

export type AssistantDocumentAttachment = {
  artifactId: string;
  title: string;
  fileName: string;
  fileType: string;
  uploadedAt: string;
  dataUrl: string;
};

type AssistantViewProps = {
  profile: AssistantProfile;
  jobs: AssistantJob[];
  applications: AssistantApplication[];
  launch: AssistantLaunch | null;
  onLaunchHandled: () => void;
  onDocumentAttached: (
    applicationId: string,
    document: AssistantDocumentAttachment,
  ) => void;
  onActionApplied: (result: AssistantAppliedAction) => void;
};

const legacyAssistantThreadsStorageKey = "tasko.assistantThreads.v1";
const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const assistantMessageMaxChars = 6_000;
const defaultAiPrivacySettings: AiPrivacySettings = {
  providerName: "OpenAI via OpenClaw/Codex",
  currentBackend: "openclaw_codex",
  consentBackend: null,
  currentConsentVersion: "2026-07-18.v2",
  hasCurrentConsent: false,
  retentionDays: 30,
};
const assistantActionMarkerPattern = /\s*<!--TASKO_ACTIONS:([A-Za-z0-9_\-=]+)-->\s*$/;

const quickActions = [
  {
    title: "Write a cover letter",
    description: "Create a focused, evidence-based draft",
    prompt: "Write a concise cover letter for this job using only evidence from my profile.",
    icon: Mail,
  },
  {
    title: "Prepare for interview",
    description: "Practice likely questions and strong answers",
    prompt: "Prepare me for an interview for this role with likely questions and answer guidance.",
    icon: Target,
  },
  {
    title: "Plan my job search",
    description: "Turn my current pipeline into next steps",
    prompt: "Review my job search context and give me a focused action plan for this week.",
    icon: BriefcaseBusiness,
  },
];

function createId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function parseSseEvent(block: string): AssistantSseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;

  try {
    const data = JSON.parse(dataLines.join("\n")) as unknown;
    return data && typeof data === "object" ? { event, data: data as Record<string, unknown> } : null;
  } catch {
    return null;
  }
}

async function consumeAssistantSse(
  response: Response,
  onEvent: (event: AssistantSseEvent) => void,
): Promise<"done" | "stopped" | "error" | null> {
  if (!response.body) throw new Error("Assistant stream has no response body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const parsed = parseSseEvent(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (parsed) {
        onEvent(parsed);
        if (["done", "stopped", "error"].includes(parsed.event)) {
          return parsed.event as "done" | "stopped" | "error";
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
    if (done) return null;
  }
}

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function readAssistantApiError(response: Response) {
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  if (typeof payload?.detail === "string" && payload.detail.trim()) return payload.detail;
  if (response.status === 413) return "This message is too long. Shorten it and try again.";
  if (response.status === 504) return "The assistant took too long to respond. Try a shorter request.";
  if (response.status === 503) return "The assistant is temporarily unavailable. Try again shortly.";
  return `Assistant request failed (HTTP ${response.status}). Please try again.`;
}

function normalizeAssistantActions(value: unknown): AssistantActionPreview[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): AssistantActionPreview[] => {
    if (!item || typeof item !== "object") return [];
    const candidate = item as Partial<AssistantActionPreview>;
    if (
      typeof candidate.id !== "string" ||
      ![
        "add_application_note",
        "update_application_next_step",
        "create_interview_event",
        "save_document",
        "update_profile_field",
      ].includes(candidate.type ?? "") ||
      typeof candidate.title !== "string" ||
      typeof candidate.description !== "string" ||
      !["profile", "job", "application"].includes(candidate.contextKind ?? "") ||
      typeof candidate.contextId !== "string" ||
      !Array.isArray(candidate.fields) ||
      !candidate.payload ||
      typeof candidate.payload !== "object"
    ) {
      return [];
    }
    const fields = candidate.fields.flatMap((field): AssistantActionFieldPreview[] => (
      field &&
      typeof field.label === "string" &&
      typeof field.before === "string" &&
      typeof field.after === "string"
        ? [field]
        : []
    ));
    return [{
      id: candidate.id,
      type: candidate.type as AssistantActionPreview["type"],
      title: candidate.title,
      description: candidate.description,
      contextKind: candidate.contextKind as AssistantContextKind,
      contextId: candidate.contextId,
      fields,
      payload: candidate.payload as Record<string, unknown>,
      status: ["preview", "applying", "applied", "error"].includes(candidate.status ?? "")
        ? candidate.status as AssistantActionPreview["status"]
        : "preview",
      resultMessage: typeof candidate.resultMessage === "string" ? candidate.resultMessage : "",
    }];
  });
}

function decodeAssistantMessage(content: string) {
  const match = content.match(assistantActionMarkerPattern);
  if (!match) return { content, actions: [] as AssistantActionPreview[] };
  try {
    const base64 = match[1].replace(/-/g, "+").replace(/_/g, "/");
    const binary = window.atob(base64);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const actions = normalizeAssistantActions(JSON.parse(new TextDecoder().decode(bytes)));
    return { content: content.replace(assistantActionMarkerPattern, "").trimEnd(), actions };
  } catch {
    return { content, actions: [] as AssistantActionPreview[] };
  }
}

function encodeAssistantMessage(message: AssistantMessage) {
  if (!message.actions?.length) return message.content;
  const bytes = new TextEncoder().encode(JSON.stringify(message.actions));
  let binary = "";
  const chunkSize = 8_192;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.slice(offset, offset + chunkSize));
  }
  const encoded = window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_");
  return `${message.content.trimEnd()}\n\n<!--TASKO_ACTIONS:${encoded}-->`;
}

function normalizeThreads(value: unknown): AssistantThread[] {
  if (!Array.isArray(value)) return [];

  return value
    .filter((item) => {
      if (!item || typeof item !== "object") return false;
      const candidate = item as Partial<AssistantThread>;
      return (
        typeof candidate.id === "string" &&
        typeof candidate.title === "string" &&
        typeof candidate.updatedAt === "string" &&
        Array.isArray(candidate.messages) &&
        ["profile", "job", "application"].includes(candidate.contextKind ?? "")
      );
    })
    .map((item) => {
      const candidate = item as AssistantThread;
      return {
        ...candidate,
        archived: Boolean(candidate.archived),
        createdAt: candidate.createdAt || candidate.updatedAt,
        providerSessionId: candidate.providerSessionId ?? null,
        messages: candidate.messages.flatMap((message): AssistantMessage[] => {
          if (
            !message ||
            typeof message.id !== "string" ||
            !["user", "assistant"].includes(message.role) ||
            typeof message.content !== "string" ||
            typeof message.createdAt !== "string"
          ) {
            return [];
          }
          const decoded = decodeAssistantMessage(message.content);
          return [{ ...message, content: decoded.content, actions: decoded.actions }];
        }),
      };
    });
}

async function fetchAssistantThreads(archived: boolean): Promise<AssistantThread[]> {
  const response = await fetch(`${apiBaseUrl}/assistant/conversations?archived=${archived}`);
  if (!response.ok) throw new Error(`Conversation loading failed with status ${response.status}`);
  return normalizeThreads(await response.json());
}

async function importLegacyThread(thread: AssistantThread) {
  const response = await fetch(
    `${apiBaseUrl}/assistant/conversations/${encodeURIComponent(thread.id)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(thread),
    },
  );
  if (!response.ok) throw new Error(`Conversation import failed with status ${response.status}`);
}

async function persistAssistantMessage(threadId: string, message: AssistantMessage) {
  const response = await fetch(
    `${apiBaseUrl}/assistant/conversations/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(message.id)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...message, content: encodeAssistantMessage(message), actions: undefined }),
    },
  );
  if (!response.ok) throw new Error(`Message persistence failed with status ${response.status}`);
}

function normalizeAssistantDocuments(value: unknown): AssistantDocument[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is AssistantDocument => {
    if (!item || typeof item !== "object") return false;
    const candidate = item as Partial<AssistantDocument>;
    return (
      typeof candidate.id === "string" &&
      ["cover_letter", "tailored_resume"].includes(candidate.type ?? "") &&
      typeof candidate.title === "string" &&
      typeof candidate.currentVersion === "number" &&
      Array.isArray(candidate.versions)
    );
  });
}

function currentDocumentContent(document: AssistantDocument) {
  return document.versions.find((version) => version.version === document.currentVersion)?.content ?? "";
}

function documentFileName(document: AssistantDocument) {
  const artifact = document.versions.find(
    (version) => version.version === document.currentVersion,
  )?.artifact;
  if (artifact?.fileName) return artifact.fileName;
  const base = document.title
    .trim()
    .normalize("NFC")
    .replace(/[^\p{L}\p{M}\p{N}._-]+/gu, "-")
    .replace(/^[._-]+|[._-]+$/g, "") || "rufina-document";
  return `${base}-v${document.currentVersion}.docx`;
}

function formatThreadDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently";

  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function createThreadTitle(prompt: string) {
  const normalized = prompt.replace(/\s+/g, " ").trim();
  if (!normalized) return "New conversation";
  return normalized.length > 42 ? `${normalized.slice(0, 42).trim()}…` : normalized;
}

function getContextLabel(
  contextKind: AssistantContextKind,
  contextId: string,
  jobs: AssistantJob[],
  applications: AssistantApplication[],
) {
  if (contextKind === "profile") return "My profile";
  if (contextKind === "job") {
    const job = jobs.find((item) => item.id === contextId);
    return job ? `${job.title} · ${job.company}` : "Select a vacancy";
  }

  const application = applications.find((item) => item.id === contextId);
  return application ? `${application.job.title} · ${application.job.company}` : "Select an application";
}

function getContextJob(
  contextKind: AssistantContextKind,
  contextId: string,
  jobs: AssistantJob[],
  applications: AssistantApplication[],
) {
  if (contextKind === "job") return jobs.find((job) => job.id === contextId) ?? null;
  if (contextKind === "application") {
    return applications.find((application) => application.id === contextId)?.job ?? null;
  }
  return null;
}

function serializeAssistantJob(job: AssistantJob | null) {
  if (!job) return null;

  return {
    id: job.id,
    title: job.title,
    company: job.company,
    location: job.location,
    type: job.type ?? "",
    match: job.match,
    overview: job.overview,
    responsibilities: job.responsibilities ?? [],
    requirements: job.requirements,
    skills: job.skills,
    aiMatch: job.aiMatch ? {
      reasons: job.aiMatch.reasons,
      gaps: job.aiMatch.gaps,
    } : null,
  };
}

function getAssistantResponse({
  prompt,
  profile,
  job,
  application,
}: {
  prompt: string;
  profile: AssistantProfile;
  job: AssistantJob | null;
  application: AssistantApplication | null;
}) {
  const normalizedPrompt = prompt.toLowerCase();
  const candidateName = profile.name.trim() || "the candidate";
  const desiredRole = profile.desired_role.trim() || profile.current_role.trim() || "your target role";
  const roleLabel = job ? `${job.title} at ${job.company}` : desiredRole;
  const skills = job?.skills.filter(Boolean).slice(0, 5) ?? [];
  const reasons = job?.aiMatch?.reasons.filter(Boolean).slice(0, 3) ?? [];
  const gaps = job?.aiMatch?.gaps.filter(Boolean).slice(0, 3) ?? [];
  const evidence = profile.experience.trim() || profile.skills.trim();

  if (normalizedPrompt.includes("cover letter") || normalizedPrompt.includes("сопровод")) {
    return [
      `Dear ${job?.company ? `${job.company} hiring team` : "Hiring Manager"},`,
      "",
      `I am applying for the ${job?.title ?? desiredRole} position. My background as ${profile.current_role || desiredRole} aligns with the role's focus${skills.length ? ` on ${skills.join(", ")}` : " and its core responsibilities"}.`,
      "",
      evidence
        ? `The strongest evidence to develop in the final version is: ${evidence.slice(0, 280)}${evidence.length > 280 ? "…" : ""}`
        : "Before sending, add one verified achievement with a measurable outcome. I have left this as guidance rather than inventing an example.",
      "",
      `I would welcome the opportunity to discuss how my experience could contribute to ${job?.company ?? "your team"}.`,
      "",
      `Best regards,\n${candidateName}`,
      "",
      "Review note: verify every claim and add one role-specific metric before sending.",
    ].join("\n");
  }

  if (normalizedPrompt.includes("interview") || normalizedPrompt.includes("интервью")) {
    const questions = [
      `Why are you interested in ${roleLabel}?`,
      `Which achievement best proves your ability to succeed in this role?`,
      skills[0] ? `Tell me about a time you used ${skills[0]} to solve a difficult problem.` : "Tell me about a difficult problem you solved.",
      gaps[0] ? `How would you address this potential gap: ${gaps[0]}?` : "What would you aim to accomplish in your first 90 days?",
      `What questions do you have for ${job?.company ?? "the hiring team"}?`,
    ];

    return [
      `Interview plan for ${roleLabel}`,
      "",
      ...questions.map((question, index) => `${index + 1}. ${question}\n   Answer with Situation → Action → Result, using only a real example from your experience.`),
      "",
      `Your strongest themes: ${reasons.length ? reasons.join("; ") : "connect your verified experience directly to the role requirements"}.`,
      "Prepare two questions about team priorities and how success will be measured in the first six months.",
    ].join("\n");
  }

  if (normalizedPrompt.includes("resume") || normalizedPrompt.includes("cv") || normalizedPrompt.includes("резюме")) {
    return [
      profile.name.trim() || "Candidate",
      `${job?.title ?? desiredRole}${profile.location ? ` · ${profile.location}` : ""}`,
      "",
      "# Professional summary",
      profile.headline.trim() || `${profile.current_role || desiredRole} targeting ${roleLabel}.`,
      "",
      "# Core skills",
      ...(profile.skills.trim()
        ? profile.skills.split(/[\n,;]+/).map((skill) => `- ${skill.trim()}`).filter((skill) => skill !== "- ")
        : skills.map((skill) => `- ${skill}`)),
      "",
      "# Experience",
      profile.experience.trim() || "Add verified experience entries from the candidate profile.",
      "",
      "# Education",
      profile.education.trim() || "Add verified education from the candidate profile.",
      "",
      gaps.length ? `Review before sending: address these gaps honestly — ${gaps.join("; ")}.` : "Review every claim before sending.",
    ].join("\n");
  }

  if (normalizedPrompt.includes("follow-up") || normalizedPrompt.includes("follow up") || normalizedPrompt.includes("recruiter")) {
    return [
      `Subject: Following up on the ${job?.title ?? desiredRole} application`,
      "",
      `Hi ${job?.company ? `${job.company} team` : "there"},`,
      "",
      `I wanted to follow up on my application for the ${job?.title ?? desiredRole} role. I remain very interested in the opportunity and would be happy to provide any additional information that would be helpful.`,
      "",
      `Thank you for your time,\n${candidateName}`,
      "",
      application?.nextStep ? `Pipeline note: current next step is “${application.nextStep}”.` : "Keep the message brief and send it only after an appropriate waiting period.",
    ].join("\n");
  }

  if (job) {
    return [
      `Current assessment: ${roleLabel} has a ${job.match}% displayed match.`,
      "",
      reasons.length ? `Strong signals:\n${reasons.map((item) => `• ${item}`).join("\n")}` : "Strong signals: compare your verified achievements with the core requirements.",
      gaps.length ? `\nGaps to review:\n${gaps.map((item) => `• ${item}`).join("\n")}` : "\nNo major gaps are recorded in the current AI match.",
      "",
      "Recommended next step: tailor the top third of the resume, verify the source vacancy, then prepare a short role-specific note.",
    ].join("\n");
  }

  return [
    `A focused plan for ${candidateName}:`,
    "",
    "1. Complete the profile and attach the latest resume.",
    "2. Prioritize a small set of roles that match your target and constraints.",
    "3. Tailor each application using verified achievements, not generic claims.",
    "4. Track follow-ups and interview preparation in the application pipeline.",
    "",
    `Current target: ${desiredRole}. Select a vacancy or application above for a more specific answer.`,
  ].join("\n");
}

export function AssistantView({
  profile,
  jobs,
  applications,
  launch,
  onLaunchHandled,
  onDocumentAttached,
  onActionApplied,
}: AssistantViewProps) {
  const [threads, setThreads] = useState<AssistantThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [draft, setDraft] = useState("");
  const [contextKind, setContextKind] = useState<AssistantContextKind>("profile");
  const [contextId, setContextId] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<AssistantConnectionStatus>("idle");
  const [streamingMessageId, setStreamingMessageId] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState("");
  const [isLoaded, setIsLoaded] = useState(false);
  const [documents, setDocuments] = useState<AssistantDocument[]>([]);
  const [documentDraft, setDocumentDraft] = useState<AssistantDocumentDraft | null>(null);
  const [isDocumentSaving, setIsDocumentSaving] = useState(false);
  const [documentError, setDocumentError] = useState("");
  const [assistantError, setAssistantError] = useState("");
  const [aiPrivacy, setAiPrivacy] = useState(defaultAiPrivacySettings);
  const [aiConsentConfirmed, setAiConsentConfirmed] = useState(false);
  const [pendingConsentPrompt, setPendingConsentPrompt] = useState<string | null>(null);
  const [pendingAutoSubmitLaunch, setPendingAutoSubmitLaunch] =
    useState<AssistantLaunch | null>(null);
  const [isSavingAiConsent, setIsSavingAiConsent] = useState(false);
  const launchedIdRef = useRef("");
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const streamAbortControllerRef = useRef<AbortController | null>(null);
  const activeRequestIdRef = useRef("");
  const stopRequestedRef = useRef(false);

  const activeThread = threads.find((thread) => thread.id === activeThreadId) ?? null;
  const selectedApplication = contextKind === "application"
    ? applications.find((application) => application.id === contextId) ?? null
    : null;
  const selectedJob = getContextJob(contextKind, contextId, jobs, applications);
  const contextLabel = getContextLabel(contextKind, contextId, jobs, applications);
  const connectionLabel = connectionStatus === "connecting"
    ? "Connecting…"
    : connectionStatus === "connected"
      ? "Connected"
      : connectionStatus === "reconnecting"
        ? "Reconnecting…"
        : connectionStatus === "disconnected"
          ? "Connection lost"
          : "Ready";

  const filteredThreads = useMemo(() => {
    const query = historyQuery.trim().toLowerCase();
    return threads
      .filter((thread) => !query || thread.title.toLowerCase().includes(query))
      .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  }, [historyQuery, threads]);

  useEffect(() => {
    let cancelled = false;

    async function loadHistory() {
      setIsLoaded(false);
      try {
        let serverThreads = await fetchAssistantThreads(showArchived);
        if (!showArchived) {
          const rawThreads = window.localStorage.getItem(legacyAssistantThreadsStorageKey);
          const legacyThreads = normalizeThreads(rawThreads ? JSON.parse(rawThreads) : []);
          if (legacyThreads.length) {
            const archivedThreads = await fetchAssistantThreads(true);
            const serverIds = new Set(
              [...serverThreads, ...archivedThreads].map((thread) => thread.id),
            );
            const threadsToImport = legacyThreads.filter((thread) => !serverIds.has(thread.id));
            await Promise.all(threadsToImport.map(importLegacyThread));
            window.localStorage.removeItem(legacyAssistantThreadsStorageKey);
            if (threadsToImport.length) serverThreads = await fetchAssistantThreads(false);
          }
        }
        if (cancelled) return;
        setThreads(serverThreads);
        setActiveThreadId(serverThreads[0]?.id ?? "");
      } catch {
        if (!cancelled) setConnectionStatus("disconnected");
      } finally {
        if (!cancelled) setIsLoaded(true);
      }
    }

    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [showArchived]);

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBaseUrl}/documents`)
      .then((response) => {
        if (!response.ok) throw new Error("Document loading failed");
        return response.json();
      })
      .then((value) => {
        if (!cancelled) setDocuments(normalizeAssistantDocuments(value));
      })
      .catch(() => {
        if (!cancelled) setDocumentError("Documents are temporarily unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBaseUrl}/privacy/ai-consent`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(await readAssistantApiError(response));
        return response.json() as Promise<AiPrivacySettings>;
      })
      .then((privacy) => {
        if (!cancelled) setAiPrivacy(privacy);
      })
      .catch((error) => {
        if (!cancelled) {
          setAssistantError(error instanceof Error ? error.message : "AI privacy settings are unavailable");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isLoaded) return;
    if (!activeThread) return;
    setContextKind(activeThread.contextKind);
    setContextId(activeThread.contextId);
  }, [activeThread?.id, isLoaded]);

  useEffect(() => {
    // A launch from Jobs must win over the conversation selected while history loads.
    // Keep it pending until that initial selection has settled, then start a fresh
    // conversation with the vacancy/application supplied by the originating action.
    if (!isLoaded || !launch || launchedIdRef.current === launch.id) return;
    launchedIdRef.current = launch.id;
    setActiveThreadId("");
    setContextKind(launch.contextKind);
    setContextId(launch.contextId ?? "");
    if (launch.autoSubmit) {
      setDraft("");
      setPendingAutoSubmitLaunch(launch);
    } else {
      setDraft(launch.prompt);
    }
    onLaunchHandled();
  }, [isLoaded, launch, onLaunchHandled]);

  useEffect(() => {
    if (
      !pendingAutoSubmitLaunch ||
      isGenerating ||
      contextKind !== pendingAutoSubmitLaunch.contextKind ||
      contextId !== (pendingAutoSubmitLaunch.contextId ?? "")
    ) {
      return;
    }
    const prompt = pendingAutoSubmitLaunch.prompt;
    setPendingAutoSubmitLaunch(null);
    void submitMessage(prompt);
  }, [
    contextId,
    contextKind,
    isGenerating,
    pendingAutoSubmitLaunch,
  ]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [activeThread?.messages.length, activeThread?.messages.at(-1)?.content, isGenerating]);

  function updateThreadContext(nextKind: AssistantContextKind, nextId: string) {
    setContextKind(nextKind);
    setContextId(nextId);
    if (!activeThread) return;

    setThreads((currentThreads) => currentThreads.map((thread) =>
      thread.id === activeThread.id
        ? { ...thread, contextKind: nextKind, contextId: nextId, updatedAt: new Date().toISOString() }
        : thread,
    ));
    void fetch(`${apiBaseUrl}/assistant/conversations/${encodeURIComponent(activeThread.id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contextKind: nextKind, contextId: nextId }),
    }).then((response) => {
      if (!response.ok) throw new Error("Conversation context update failed");
    }).catch(() => setConnectionStatus("disconnected"));
  }

  function startNewChat() {
    if (showArchived) setShowArchived(false);
    setActiveThreadId("");
    setDraft("");
    setContextKind("profile");
    setContextId("");
  }

  async function deleteThread(threadId: string) {
    if (isGenerating && activeThreadId === threadId) return;
    try {
      const response = await fetch(
        `${apiBaseUrl}/assistant/conversations/${encodeURIComponent(threadId)}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error("Conversation deletion failed");
    } catch {
      setConnectionStatus("disconnected");
      return;
    }
    setThreads((currentThreads) => currentThreads.filter((thread) => thread.id !== threadId));
    if (activeThreadId === threadId) setActiveThreadId("");
  }

  async function setThreadArchived(threadId: string, archived: boolean) {
    if (isGenerating && activeThreadId === threadId) return;
    try {
      const response = await fetch(
        `${apiBaseUrl}/assistant/conversations/${encodeURIComponent(threadId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ archived }),
        },
      );
      if (!response.ok) throw new Error("Conversation archive update failed");
    } catch {
      setConnectionStatus("disconnected");
      return;
    }
    setThreads((currentThreads) => currentThreads.filter((thread) => thread.id !== threadId));
    if (activeThreadId === threadId) setActiveThreadId("");
  }

  function openDocumentFromMessage(message: AssistantMessage) {
    const roleLabel = selectedJob
      ? `${selectedJob.title} · ${selectedJob.company}`
      : profile.desired_role || profile.current_role || "Job search";
    setDocumentDraft({
      id: "",
      type: "cover_letter",
      title: `Cover letter · ${roleLabel}`,
      content: message.content,
      jobId: selectedJob?.id ?? "",
      applicationId: selectedApplication?.id ?? "",
    });
    setDocumentError("");
  }

  function openSavedDocument(document: AssistantDocument) {
    if (document.type !== "cover_letter") return;
    setDocumentDraft({
      id: document.id,
      type: document.type,
      title: document.title,
      content: currentDocumentContent(document),
      jobId: document.jobId ?? "",
      applicationId: document.applicationIds[0] ?? "",
    });
    setDocumentError("");
  }

  async function saveDocumentArtifact() {
    if (!documentDraft?.title.trim() || !documentDraft.content.trim()) return;
    setIsDocumentSaving(true);
    setDocumentError("");
    try {
      const isExisting = Boolean(documentDraft.id);
      const response = await fetch(
        isExisting
          ? `${apiBaseUrl}/documents/${encodeURIComponent(documentDraft.id)}`
          : `${apiBaseUrl}/documents`,
        {
          method: isExisting ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...(isExisting ? {} : { type: documentDraft.type }),
            title: documentDraft.title.trim(),
            content: documentDraft.content.trim(),
            jobId: documentDraft.jobId || null,
            ...(!isExisting && documentDraft.applicationId
              ? { applicationId: documentDraft.applicationId }
              : {}),
          }),
        },
      );
      if (!response.ok) throw new Error("Document save failed");
      let savedDocument = (await response.json()) as AssistantDocument;

      if (
        isExisting &&
        documentDraft.applicationId &&
        !savedDocument.applicationIds.includes(documentDraft.applicationId)
      ) {
        const attachResponse = await fetch(
          `${apiBaseUrl}/documents/${encodeURIComponent(savedDocument.id)}/attachments`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ applicationId: documentDraft.applicationId }),
          },
        );
        if (!attachResponse.ok) throw new Error("Document attachment failed");
        savedDocument = (await attachResponse.json()) as AssistantDocument;
      }

      setDocuments((currentDocuments) => [
        savedDocument,
        ...currentDocuments.filter((document) => document.id !== savedDocument.id),
      ]);
      if (documentDraft.applicationId) {
        onDocumentAttached(documentDraft.applicationId, {
          artifactId: savedDocument.id,
          title: savedDocument.title,
          fileName: documentFileName(savedDocument),
          fileType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          uploadedAt: savedDocument.updatedAt,
          dataUrl: `${apiBaseUrl}/documents/${encodeURIComponent(savedDocument.id)}/download`,
        });
      }
      setDocumentDraft(null);
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : "Document save failed");
    } finally {
      setIsDocumentSaving(false);
    }
  }

  async function restoreDocumentVersion(documentId: string, version: number) {
    setIsDocumentSaving(true);
    setDocumentError("");
    try {
      const response = await fetch(
        `${apiBaseUrl}/documents/${encodeURIComponent(documentId)}/restore`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ version }),
        },
      );
      if (!response.ok) throw new Error("Version restore failed");
      const restored = (await response.json()) as AssistantDocument;
      setDocuments((currentDocuments) => [
        restored,
        ...currentDocuments.filter((document) => document.id !== restored.id),
      ]);
      setDocumentDraft((currentDraft) => currentDraft
        ? { ...currentDraft, content: currentDocumentContent(restored) }
        : currentDraft);
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : "Version restore failed");
    } finally {
      setIsDocumentSaving(false);
    }
  }

  async function deleteDocumentArtifact(documentId: string) {
    if (!window.confirm("Delete this document and all its versions?")) return;
    try {
      const response = await fetch(
        `${apiBaseUrl}/documents/${encodeURIComponent(documentId)}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error("Document deletion failed");
      setDocuments((currentDocuments) => currentDocuments.filter((document) => document.id !== documentId));
      setDocumentDraft(null);
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : "Document deletion failed");
    }
  }

  function setMessageActionState(
    threadId: string,
    messageId: string,
    actionId: string,
    status: AssistantActionPreview["status"],
    resultMessage = "",
  ) {
    setThreads((currentThreads) => currentThreads.map((thread) =>
      thread.id === threadId
        ? {
            ...thread,
            messages: thread.messages.map((message) =>
              message.id === messageId
                ? {
                    ...message,
                    actions: message.actions?.map((action) =>
                      action.id === actionId ? { ...action, status, resultMessage } : action,
                    ),
                  }
                : message,
            ),
          }
        : thread,
    ));
  }

  async function applyAssistantAction(message: AssistantMessage, action: AssistantActionPreview) {
    if (!activeThread || action.status === "applying" || action.status === "applied") return;
    const threadId = activeThread.id;
    setMessageActionState(threadId, message.id, action.id, "applying");

    try {
      const response = await fetch(`${apiBaseUrl}/assistant/actions/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: {
            ...action,
            status: "preview",
            resultMessage: "",
          },
        }),
      });
      const value = await response.json().catch(() => null) as AssistantAppliedAction | { detail?: string } | null;
      if (!response.ok || !value || !("resourceKind" in value)) {
        throw new Error(value && "detail" in value && typeof value.detail === "string" ? value.detail : "Action could not be applied");
      }

      const result = value as AssistantAppliedAction;
      const completedMessage: AssistantMessage = {
        ...message,
        actions: message.actions?.map((item) =>
          item.id === action.id
            ? { ...item, status: "applied", resultMessage: result.message }
            : item,
        ),
      };
      setMessageActionState(threadId, message.id, action.id, "applied", result.message);
      await persistAssistantMessage(threadId, completedMessage);

      if (result.resourceKind === "document") {
        const savedDocument = normalizeAssistantDocuments([result.resource])[0];
        if (savedDocument) {
          setDocuments((currentDocuments) => [
            savedDocument,
            ...currentDocuments.filter((document) => document.id !== savedDocument.id),
          ]);
          const applicationId = typeof action.payload.applicationId === "string"
            ? action.payload.applicationId
            : "";
          if (applicationId) {
            onDocumentAttached(applicationId, {
              artifactId: savedDocument.id,
              title: savedDocument.title,
              fileName: documentFileName(savedDocument),
              fileType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              uploadedAt: savedDocument.updatedAt,
              dataUrl: `${apiBaseUrl}/documents/${encodeURIComponent(savedDocument.id)}/download`,
            });
          }
        }
      }
      onActionApplied(result);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Action could not be applied";
      const failedMessage: AssistantMessage = {
        ...message,
        actions: message.actions?.map((item) =>
          item.id === action.id
            ? { ...item, status: "error", resultMessage: errorMessage }
            : item,
        ),
      };
      setMessageActionState(threadId, message.id, action.id, "error", errorMessage);
      void persistAssistantMessage(threadId, failedMessage).catch(() => setConnectionStatus("disconnected"));
    }
  }

  async function submitMessage(explicitPrompt?: string, consentGranted = false) {
    const prompt = (explicitPrompt ?? draft).trim();
    if (!prompt || isGenerating) return;
    if (prompt.length > assistantMessageMaxChars) {
      setAssistantError(`Message is too long. The limit is ${assistantMessageMaxChars.toLocaleString()} characters.`);
      return;
    }
    if (!aiPrivacy.hasCurrentConsent && !consentGranted) {
      setAiConsentConfirmed(false);
      setPendingConsentPrompt(prompt);
      return;
    }
    setAssistantError("");

    const now = new Date().toISOString();
    const threadId = activeThread?.id ?? createId("assistant-thread");
    const userMessage: AssistantMessage = {
      id: createId("assistant-user"),
      role: "user",
      content: prompt,
      createdAt: now,
      status: "complete",
    };
    const assistantMessageId = createId("assistant-response");
    const pendingAssistantMessage: AssistantMessage = {
      id: assistantMessageId,
      role: "assistant",
      content: "",
      createdAt: now,
      status: "generating",
    };
    if (activeThread) {
      setThreads((currentThreads) => currentThreads.map((thread) =>
        thread.id === threadId
          ? { ...thread, messages: [...thread.messages, userMessage, pendingAssistantMessage], updatedAt: now }
          : thread,
      ));
    } else {
      setThreads((currentThreads) => [{
        id: threadId,
        title: createThreadTitle(prompt),
        contextKind,
        contextId,
        archived: false,
        createdAt: now,
        updatedAt: now,
        messages: [userMessage, pendingAssistantMessage],
      }, ...currentThreads]);
      setActiveThreadId(threadId);
    }

    setDraft("");
    setIsGenerating(true);
    setStreamingMessageId(assistantMessageId);
    setConnectionStatus("connecting");
    stopRequestedRef.current = false;
    const requestId = createId("assistant-stream");
    activeRequestIdRef.current = requestId;
    const abortController = new AbortController();
    streamAbortControllerRef.current = abortController;
    let streamedContent = "";
    let offset = 0;
    let completed = false;
    let terminalError = "";
    let completedActions: AssistantActionPreview[] = [];
    let streamBackend: AssistantMessage["source"] = "openclaw_codex";
    const requestPayload = {
      requestId,
      threadId,
      userMessageId: userMessage.id,
      assistantMessageId,
      conversationTitle: activeThread?.title ?? createThreadTitle(prompt),
      message: prompt,
      contextKind,
      contextId,
      job: serializeAssistantJob(selectedJob),
      application: selectedApplication ? {
        id: selectedApplication.id,
        status: selectedApplication.status,
        notes: selectedApplication.notes,
        nextStep: selectedApplication.nextStep,
        job: serializeAssistantJob(selectedApplication.job),
      } : null,
    };

    const updateAssistantMessage = (
      content: string,
      source?: AssistantMessage["source"],
      actions?: AssistantActionPreview[],
      messageStatus: AssistantMessage["status"] = "complete",
    ) => {
      const updatedAt = new Date().toISOString();
      setThreads((currentThreads) => currentThreads.map((thread) =>
        thread.id === threadId
          ? {
              ...thread,
              updatedAt,
              messages: thread.messages.map((message) =>
                message.id === assistantMessageId
                  ? {
                      ...message,
                      content,
                      source,
                      status: messageStatus,
                      createdAt: updatedAt,
                      ...(actions ? { actions } : {}),
                    }
                  : message,
              ),
            }
          : thread,
      ));
    };

    try {
      for (let attempt = 0; attempt < 4 && !completed; attempt += 1) {
        if (attempt > 0) {
          setConnectionStatus("reconnecting");
          await wait(Math.min(400 * (2 ** (attempt - 1)), 1600));
        }

        try {
          const apiResponse = await fetch(`${apiBaseUrl}/assistant/chat/stream`, {
            method: "POST",
            headers: {
              Accept: "text/event-stream",
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ ...requestPayload, offset }),
            signal: abortController.signal,
          });
          if (!apiResponse.ok) {
            throw new Error(await readAssistantApiError(apiResponse));
          }

          const terminalEvent = await consumeAssistantSse(apiResponse, ({ event, data }) => {
            if (event === "connected") {
              setConnectionStatus("connected");
              return;
            }
            if (event === "delta" && typeof data.text === "string" && typeof data.offset === "number") {
              streamedContent += data.text;
              offset = data.offset;
              updateAssistantMessage(streamedContent, streamBackend);
              return;
            }
            if (event === "error") {
              terminalError = typeof data.message === "string" ? data.message : "Assistant generation failed";
              return;
            }
            if (event === "done" && data.metadata && typeof data.metadata === "object") {
              const metadata = data.metadata as Record<string, unknown>;
              if (metadata.backend === "openclaw_codex" || metadata.backend === "openai_api") {
                streamBackend = metadata.backend;
              }
              if (typeof metadata.sessionKey === "string") {
                setThreads((currentThreads) => currentThreads.map((thread) =>
                  thread.id === threadId
                    ? { ...thread, providerSessionId: metadata.sessionKey as string }
                    : thread,
                ));
              }
              completedActions = normalizeAssistantActions(metadata.actions);
            }
          });

          if (terminalEvent === "done") {
            completed = true;
            updateAssistantMessage(streamedContent.trim(), streamBackend, completedActions);
          } else if (terminalEvent === "stopped") {
            completed = true;
          } else if (terminalEvent === "error") {
            throw new Error(terminalError || "Assistant generation failed");
          } else {
            throw new Error("Assistant stream disconnected");
          }
        } catch (error) {
          if (stopRequestedRef.current || abortController.signal.aborted) throw error;
          if (attempt === 3 || terminalError) throw error;
        }
      }
    } catch (error) {
      if (stopRequestedRef.current) {
        if (!streamedContent) {
          setThreads((currentThreads) => currentThreads.map((thread) =>
            thread.id === threadId
              ? { ...thread, messages: thread.messages.filter((message) => message.id !== assistantMessageId) }
              : thread,
          ));
        }
        setConnectionStatus("idle");
      } else {
        const errorMessage = terminalError || (error instanceof Error
          ? error.message
          : "The assistant could not complete the request. Please try again.");
        setAssistantError(errorMessage);
        updateAssistantMessage(
          streamedContent || errorMessage,
          streamedContent ? streamBackend : undefined,
          undefined,
          "error",
        );
        setConnectionStatus("disconnected");
      }
    } finally {
      setIsGenerating(false);
      setStreamingMessageId("");
      streamAbortControllerRef.current = null;
      activeRequestIdRef.current = "";
      if (completed) setConnectionStatus("idle");
    }
  }

  async function grantAiConsent() {
    if (!aiConsentConfirmed || !pendingConsentPrompt) return;
    setIsSavingAiConsent(true);
    try {
      const response = await fetch(`${apiBaseUrl}/privacy/ai-consent`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          version: aiPrivacy.currentConsentVersion,
          backend: aiPrivacy.currentBackend,
          retentionDays: aiPrivacy.retentionDays,
        }),
      });
      if (!response.ok) throw new Error(await readAssistantApiError(response));
      const privacy = await response.json() as AiPrivacySettings;
      const prompt = pendingConsentPrompt;
      setAiPrivacy(privacy);
      setPendingConsentPrompt(null);
      void submitMessage(prompt, true);
    } catch (error) {
      setAssistantError(error instanceof Error ? error.message : "AI consent could not be saved");
    } finally {
      setIsSavingAiConsent(false);
    }
  }

  async function revokeAiConsent() {
    try {
      const response = await fetch(`${apiBaseUrl}/privacy/ai-consent`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readAssistantApiError(response));
      setAiPrivacy((privacy) => ({ ...privacy, hasCurrentConsent: false }));
      setAiConsentConfirmed(false);
      setThreads([]);
      setActiveThreadId("");
      setDocuments([]);
    } catch (error) {
      setAssistantError(error instanceof Error ? error.message : "AI consent could not be revoked");
    }
  }

  async function stopGenerating() {
    const requestId = activeRequestIdRef.current;
    if (!requestId || !isGenerating) return;
    stopRequestedRef.current = true;
    streamAbortControllerRef.current?.abort();
    setConnectionStatus("idle");
    try {
      await fetch(`${apiBaseUrl}/assistant/chat/stream/${encodeURIComponent(requestId)}`, {
        method: "DELETE",
      });
    } catch {
      // The local abort already stopped rendering; the server expires orphaned streams.
    }
  }

  function regenerateMessage(messageId: string) {
    if (!activeThread || isGenerating) return;
    const messageIndex = activeThread.messages.findIndex((message) => message.id === messageId);
    const previousUserMessage = [...activeThread.messages.slice(0, messageIndex)].reverse().find((message) => message.role === "user");
    if (!previousUserMessage) return;

    setThreads((currentThreads) => currentThreads.map((thread) =>
      thread.id === activeThread.id
        ? { ...thread, messages: thread.messages.filter((message) => message.id !== messageId) }
        : thread,
    ));
    void fetch(
      `${apiBaseUrl}/assistant/conversations/${encodeURIComponent(activeThread.id)}/messages/${encodeURIComponent(messageId)}`,
      { method: "DELETE" },
    ).then((response) => {
      if (!response.ok) throw new Error("Message deletion failed");
    }).catch(() => setConnectionStatus("disconnected"));
    setDraft(previousUserMessage.content);
  }

  async function copyMessage(message: AssistantMessage) {
    await navigator.clipboard?.writeText(message.content);
    setCopiedMessageId(message.id);
    window.setTimeout(() => setCopiedMessageId(""), 1400);
  }

  return (
    <>
    <section className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-3 flex shrink-0 items-start justify-between gap-3 2xl:mb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-[#ff6b12] to-[#e43d00] text-white shadow-[0_10px_28px_rgba(255,90,0,0.28)]">
              <Sparkles className="h-[18px] w-[18px]" />
            </span>
            <div>
              <h1 className="text-[24px] font-bold leading-tight text-white sm:text-[27px] 2xl:text-[31px]">AI Assistant</h1>
              <p className="mt-0.5 text-[12px] text-muted 2xl:text-sm">Your context-aware job search workspace</p>
            </div>
          </div>
        </div>
        <Button onClick={startNewChat} disabled={isGenerating} className="h-9 rounded-md bg-gradient-to-r from-[#ff5a00] to-[#dd3d00] px-3 text-xs 2xl:h-10 2xl:text-sm">
          <MessageSquarePlus className="h-4 w-4" /> New chat
        </Button>
      </header>

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[210px_minmax(0,1fr)] xl:grid-cols-[220px_minmax(0,1fr)_260px] 2xl:grid-cols-[250px_minmax(0,1fr)_290px] 2xl:gap-4">
        <aside className="panel hidden min-h-0 overflow-hidden lg:flex lg:flex-col">
          <div className="border-b border-border p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-muted">
                {showArchived ? "Archived" : "Conversations"}
              </p>
              <button
                type="button"
                onClick={() => setShowArchived((value) => !value)}
                className="flex items-center gap-1 rounded px-1.5 py-1 text-[9px] font-bold uppercase tracking-wide text-muted transition hover:bg-white/10 hover:text-white"
              >
                {showArchived ? <ArchiveRestore className="h-3 w-3" /> : <Archive className="h-3 w-3" />}
                {showArchived ? "Active" : "Archive"}
              </button>
            </div>
            <label className="mt-2.5 flex h-9 items-center gap-2 rounded-md border border-border bg-white/[0.035] px-2.5 focus-within:border-accent/60">
              <Search className="h-3.5 w-3.5 text-muted" />
              <input value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="Search history" className="min-w-0 flex-1 bg-transparent text-xs text-white outline-none placeholder:text-muted" />
            </label>
          </div>
          <div className="job-scroll min-h-0 flex-1 overflow-y-auto p-2">
            {filteredThreads.length ? filteredThreads.map((thread) => (
              <div key={thread.id} className={cn("group relative mb-1 rounded-md border transition", thread.id === activeThreadId ? "border-accent/35 bg-accent/10" : "border-transparent hover:border-border hover:bg-white/[0.035]")}>
                <button type="button" onClick={() => setActiveThreadId(thread.id)} className="w-full p-2.5 pr-14 text-left">
                  <p className="line-clamp-2 text-xs font-bold leading-4 text-[#e7ebf2]">{thread.title}</p>
                  <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-muted">
                    <span className="truncate">{getContextLabel(thread.contextKind, thread.contextId, jobs, applications)}</span>
                    <span className="shrink-0">{formatThreadDate(thread.updatedAt)}</span>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setThreadArchived(thread.id, !showArchived)}
                  aria-label={showArchived ? "Restore conversation" : "Archive conversation"}
                  className="absolute right-7 top-2 rounded p-1 text-muted opacity-0 transition hover:bg-white/10 hover:text-white group-hover:opacity-100"
                >
                  {showArchived ? <ArchiveRestore className="h-3.5 w-3.5" /> : <Archive className="h-3.5 w-3.5" />}
                </button>
                <button type="button" onClick={() => deleteThread(thread.id)} aria-label="Delete conversation" className="absolute right-1.5 top-2 rounded p-1 text-muted opacity-0 transition hover:bg-white/10 hover:text-white group-hover:opacity-100">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            )) : (
              <div className="px-2 py-8 text-center">
                <Bot className="mx-auto h-6 w-6 text-muted" />
                <p className="mt-2 text-xs font-semibold text-muted">
                  {!isLoaded ? "Loading conversations…" : showArchived ? "No archived conversations" : "No conversations yet"}
                </p>
              </div>
            )}
          </div>
        </aside>

        <main className="panel flex min-h-0 min-w-0 flex-col overflow-hidden">
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-2.5 2xl:px-4 2xl:py-3">
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-muted">Context</span>
            <div className="relative">
              <select
                value={contextKind}
                onChange={(event) => {
                  const nextKind = event.target.value as AssistantContextKind;
                  const nextId = nextKind === "job" ? jobs[0]?.id ?? "" : nextKind === "application" ? applications[0]?.id ?? "" : "";
                  updateThreadContext(nextKind, nextId);
                }}
                className="h-8 appearance-none rounded-md border border-border bg-[#151c24] pl-2.5 pr-7 text-xs font-bold text-white outline-none focus:border-accent/60"
              >
                <option value="profile">My profile</option>
                <option value="job" disabled={!jobs.length}>Vacancy</option>
                <option value="application" disabled={!applications.length}>Application</option>
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-2 h-4 w-4 text-muted" />
            </div>
            {contextKind !== "profile" && (
              <div className="relative min-w-0 flex-1 sm:max-w-[390px]">
                <select
                  value={contextId}
                  onChange={(event) => updateThreadContext(contextKind, event.target.value)}
                  className="h-8 w-full appearance-none truncate rounded-md border border-border bg-[#151c24] pl-2.5 pr-7 text-xs font-semibold text-[#dfe4ec] outline-none focus:border-accent/60"
                >
                  {contextKind === "job" ? jobs.map((job) => <option key={job.id} value={job.id}>{job.title} · {job.company}</option>) : applications.map((application) => <option key={application.id} value={application.id}>{application.job.title} · {application.job.company}</option>)}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-2 h-4 w-4 text-muted" />
              </div>
            )}
            <span className={cn(
              "ml-auto hidden items-center gap-1.5 text-[10px] font-semibold sm:inline-flex",
              connectionStatus === "connected" && "text-success",
              ["connecting", "reconnecting"].includes(connectionStatus) && "text-amber-400",
              connectionStatus === "disconnected" && "text-red-400",
              connectionStatus === "idle" && "text-muted",
            )}>
              <span className={cn(
                "h-1.5 w-1.5 rounded-full",
                connectionStatus === "connected" && "bg-success",
                ["connecting", "reconnecting"].includes(connectionStatus) && "animate-pulse bg-amber-400",
                connectionStatus === "disconnected" && "bg-red-400",
                connectionStatus === "idle" && "bg-muted",
              )} /> {connectionLabel}
            </span>
          </div>

          <div className="job-scroll min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-5 2xl:px-7 2xl:py-6">
            {!activeThread?.messages.length ? (
              <div className="mx-auto flex min-h-full max-w-[720px] flex-col justify-center py-4">
                <div className="text-center">
                  <span className="mx-auto grid h-12 w-12 place-items-center rounded-xl border border-accent/30 bg-accent/10 text-accent">
                    <Bot className="h-6 w-6" />
                  </span>
                  <h2 className="mt-3 text-xl font-bold text-white 2xl:text-2xl">What are we working on?</h2>
                  <p className="mx-auto mt-1.5 max-w-[540px] text-xs leading-5 text-muted 2xl:text-sm">I use your selected profile, vacancy, or application to make every answer specific and evidence-based.</p>
                </div>
                <div className="mt-5 grid gap-2 sm:grid-cols-2 2xl:mt-6 2xl:gap-3">
                  {quickActions.map((action) => (
                    <button key={action.title} type="button" disabled={showArchived} onClick={() => submitMessage(action.prompt)} className="group rounded-lg border border-border bg-white/[0.025] p-3 text-left transition hover:border-accent/40 hover:bg-accent/[0.07] disabled:cursor-not-allowed disabled:opacity-40 2xl:p-4">
                      <span className="grid h-8 w-8 place-items-center rounded-md bg-accent/12 text-accent transition group-hover:bg-accent/20"><action.icon className="h-4 w-4" /></span>
                      <p className="mt-2.5 text-sm font-bold text-white">{action.title}</p>
                      <p className="mt-1 text-[11px] leading-4 text-muted 2xl:text-xs">{action.description}</p>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mx-auto max-w-[760px] space-y-5">
                {activeThread.messages.map((message) => (
                  <article key={message.id} className={cn("flex gap-2.5 sm:gap-3", message.role === "user" && "justify-end")}>
                    {message.role === "assistant" && <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent/15 text-accent"><Bot className="h-4 w-4" /></span>}
                    <div className={cn("min-w-0 max-w-[88%]", message.role === "user" && "rounded-xl rounded-tr-sm bg-accent px-3.5 py-2.5 text-white shadow-[0_8px_24px_rgba(255,90,0,0.14)]")}>
                      {message.role === "assistant" && (
                        <p className="mb-1.5 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.1em] text-accent">
                          Rufina Assistant
                          {message.source && (
                            <span className="rounded border border-border bg-white/[0.035] px-1.5 py-0.5 text-[8px] tracking-[0.08em] text-muted">
                              {getAiSourceLabel(message.source)}
                            </span>
                          )}
                        </p>
                      )}
                      <p className={cn("whitespace-pre-wrap text-[13px] leading-5 2xl:text-sm 2xl:leading-6", message.role === "assistant" ? "text-[#e4e9f1]" : "text-white")}>
                        {message.content}
                        {message.id === streamingMessageId && message.content && <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-accent align-middle" />}
                        {message.id === streamingMessageId && !message.content && (
                          <span className="flex gap-1 py-1">
                            <i className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted" />
                            <i className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:120ms]" />
                            <i className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:240ms]" />
                          </span>
                        )}
                      </p>
                      {message.role === "assistant" && message.id !== streamingMessageId && message.actions?.length ? (
                        <div className="mt-3 space-y-2.5">
                          {message.actions.map((action) => {
                            const isApplied = action.status === "applied";
                            const isApplying = action.status === "applying";
                            return (
                              <section
                                key={action.id}
                                className={cn(
                                  "rounded-lg border p-3",
                                  isApplied
                                    ? "border-success/35 bg-success/[0.055]"
                                    : "border-accent/35 bg-accent/[0.055]",
                                )}
                              >
                                <div className="flex items-start gap-2.5">
                                  <span className={cn(
                                    "grid h-8 w-8 shrink-0 place-items-center rounded-md",
                                    isApplied ? "bg-success/15 text-success" : "bg-accent/15 text-accent",
                                  )}>
                                    {isApplied ? <Check className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
                                  </span>
                                  <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <p className="text-xs font-bold text-white">{action.title}</p>
                                      <span className={cn(
                                        "rounded border px-1.5 py-0.5 text-[8px] font-black uppercase tracking-wide",
                                        isApplied
                                          ? "border-success/35 bg-success/10 text-success"
                                          : "border-accent/35 bg-accent/10 text-accent",
                                      )}>
                                        {isApplied ? "Applied" : "Preview"}
                                      </span>
                                    </div>
                                    <p className="mt-1 text-[10px] leading-4 text-muted">{action.description}</p>
                                  </div>
                                </div>
                                <div className="mt-2.5 space-y-2 rounded-md border border-border bg-black/10 p-2.5">
                                  {action.fields.map((field) => (
                                    <div key={`${action.id}-${field.label}`}>
                                      <p className="text-[9px] font-black uppercase tracking-wide text-muted">{field.label}</p>
                                      {field.before ? (
                                        <p className="mt-1 max-h-20 overflow-y-auto whitespace-pre-wrap text-[10px] leading-4 text-muted line-through decoration-white/25">{field.before}</p>
                                      ) : null}
                                      <p className="mt-1 max-h-36 overflow-y-auto whitespace-pre-wrap text-[10px] leading-4 text-[#e8edf4]">{field.after || "Empty"}</p>
                                    </div>
                                  ))}
                                </div>
                                <div className="mt-2.5 flex items-center justify-between gap-2">
                                  <p className={cn(
                                    "min-w-0 text-[9px] leading-4",
                                    action.status === "error" ? "text-red-300" : isApplied ? "text-success" : "text-muted",
                                  )}>
                                    {action.resultMessage || (isApplied ? "Change applied" : "Nothing changes until you confirm.")}
                                  </p>
                                  {!isApplied ? (
                                    <Button
                                      type="button"
                                      size="sm"
                                      disabled={isApplying}
                                      aria-label={`Apply ${action.title}`}
                                      onClick={() => applyAssistantAction(message, action)}
                                      className="h-8 shrink-0 rounded-md bg-accent px-3 text-[10px] font-bold text-white hover:bg-[#ff6b12] disabled:opacity-50"
                                    >
                                      {isApplying ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                                      {isApplying ? "Applying…" : action.status === "error" ? "Try again" : "Apply"}
                                    </Button>
                                  ) : null}
                                </div>
                              </section>
                            );
                          })}
                        </div>
                      ) : null}
                      {message.role === "assistant" && message.id !== streamingMessageId && message.content && (
                        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-border pt-2">
                          <Button variant="ghost" size="sm" onClick={() => copyMessage(message)} className="h-7 px-2 text-[10px] text-muted hover:text-white">
                            {copiedMessageId === message.id ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />} {copiedMessageId === message.id ? "Copied" : "Copy"}
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => regenerateMessage(message.id)} className="h-7 px-2 text-[10px] text-muted hover:text-white">
                            <RefreshCw className="h-3.5 w-3.5" /> Regenerate
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => openDocumentFromMessage(message)} className="h-7 px-2 text-[10px] text-muted hover:text-white">
                            <Save className="h-3.5 w-3.5" /> Save as cover letter
                          </Button>
                        </div>
                      )}
                    </div>
                    {message.role === "user" && <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-white/[0.08] text-[#dfe4ec]"><UserRound className="h-4 w-4" /></span>}
                  </article>
                ))}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-border p-3 2xl:p-4">
            {assistantError ? (
              <div className="mx-auto mb-2 flex max-w-[780px] items-start gap-2 rounded-md border border-red-400/30 bg-red-500/10 px-3 py-2 text-[11px] leading-4 text-red-200">
                <span className="min-w-0 flex-1">{assistantError}</span>
                <button type="button" onClick={() => setAssistantError("")} aria-label="Dismiss assistant error" className="shrink-0 text-red-300 hover:text-white">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : null}
            <div className="mx-auto max-w-[780px] rounded-lg border border-border bg-white/[0.035] p-2 shadow-[0_12px_34px_rgba(0,0,0,0.18)] focus-within:border-accent/60">
              <textarea
                value={draft}
                disabled={showArchived}
                maxLength={assistantMessageMaxChars}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submitMessage();
                  }
                }}
                rows={2}
                placeholder={showArchived ? "Restore a conversation to continue…" : "Ask anything about your job search…"}
                className="max-h-32 min-h-[42px] w-full resize-none bg-transparent px-2 py-1 text-[13px] leading-5 text-white outline-none placeholder:text-muted 2xl:text-sm"
              />
              <div className="flex items-center justify-between gap-2 px-1">
                <p className="truncate text-[10px] text-muted">
                  Using: {contextLabel}
                  {draft.length >= assistantMessageMaxChars * 0.8 ? ` · ${draft.length.toLocaleString()}/${assistantMessageMaxChars.toLocaleString()}` : ""}
                </p>
                {isGenerating ? (
                  <Button onClick={stopGenerating} aria-label="Stop generating" className="h-8 rounded-md border border-red-400/30 bg-red-500/10 px-2.5 text-[10px] font-bold text-red-300 hover:bg-red-500/20">
                    <Square className="h-3 w-3 fill-current" /> Stop generating
                  </Button>
                ) : (
                  <Button onClick={() => submitMessage()} disabled={showArchived || !draft.trim()} aria-label="Send message" className="h-8 w-8 rounded-md bg-accent p-0 text-white hover:bg-[#ff6b12] disabled:opacity-40">
                    <Send className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
            <p className="mt-1.5 text-center text-[9px] text-muted">Rufina may make mistakes. Verify generated claims before using them. {aiPrivacy.hasCurrentConsent ? <button type="button" onClick={() => void revokeAiConsent()} className="font-bold text-amber-200 hover:text-white">Revoke AI consent</button> : <span className="font-bold text-amber-200">AI consent required</span>}</p>
          </div>
        </main>

        <aside className="panel hidden min-h-0 overflow-y-auto xl:block">
          <div className="border-b border-border p-3.5 2xl:p-4">
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-muted">Active context</p>
            <div className="mt-3 rounded-lg border border-accent/25 bg-accent/[0.07] p-3">
              <span className="grid h-8 w-8 place-items-center rounded-md bg-accent/16 text-accent">
                {contextKind === "profile" ? <UserRound className="h-4 w-4" /> : contextKind === "job" ? <BriefcaseBusiness className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
              </span>
              <p className="mt-2.5 text-sm font-bold leading-5 text-white">{contextLabel}</p>
              {selectedJob && <p className="mt-1 text-[11px] text-muted">{selectedJob.location} · {selectedJob.match}% match</p>}
              {selectedApplication && <span className="mt-2 inline-flex rounded-md border border-border bg-white/[0.04] px-2 py-1 text-[10px] font-bold capitalize text-[#dfe4ec]">{selectedApplication.status}</span>}
            </div>
          </div>

          <div className="border-b border-border p-3.5 2xl:p-4">
            <p className="text-xs font-bold text-white">Sources available</p>
            <div className="mt-3 space-y-2.5">
              {[
                { label: "Candidate profile", ready: Boolean(profile.name || profile.current_role || profile.skills) },
                { label: "Resume", ready: Boolean(profile.resume_file_name) },
                { label: "Vacancy details", ready: Boolean(selectedJob) },
                { label: "Application notes", ready: Boolean(selectedApplication?.notes) },
              ].map((source) => (
                <div key={source.label} className="flex items-center gap-2 text-[11px]">
                  <span className={cn("grid h-4 w-4 place-items-center rounded-full border", source.ready ? "border-success/40 bg-success/12 text-success" : "border-border text-muted")}>
                    {source.ready ? <Check className="h-2.5 w-2.5" /> : <span className="h-1 w-1 rounded-full bg-current" />}
                  </span>
                  <span className={source.ready ? "text-[#dfe4ec]" : "text-muted"}>{source.label}</span>
                  <span className="ml-auto text-[9px] font-bold uppercase text-muted">{source.ready ? "Ready" : "Missing"}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="border-b border-border p-3.5 2xl:p-4">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-bold text-white">Saved documents</p>
              <span className="text-[9px] font-bold uppercase text-muted">{documents.length}</span>
            </div>
            {documentError && !documentDraft ? (
              <p className="mt-2 text-[10px] leading-4 text-red-300">{documentError}</p>
            ) : null}
            <div className="mt-2 space-y-1.5">
              {documents.length ? documents.slice(0, 5).map((document) => (
                <div key={document.id} className="flex items-center gap-1.5 rounded-md border border-border bg-white/[0.025] p-2">
                  {document.type === "cover_letter" ? <button type="button" onClick={() => openSavedDocument(document)} className="min-w-0 flex-1 text-left">
                    <p className="truncate text-[10px] font-bold text-[#e2e7ef]">{document.title}</p>
                    <p className="mt-0.5 text-[9px] text-muted">
                      Cover letter · v{document.currentVersion}
                    </p>
                  </button> : <div className="min-w-0 flex-1">
                    <p className="truncate text-[10px] font-bold text-[#e2e7ef]">{document.title}</p>
                    <p className="mt-0.5 text-[9px] text-muted">Historical resume · download only · v{document.currentVersion}</p>
                  </div>}
                  <a
                    href={`${apiBaseUrl}/documents/${encodeURIComponent(document.id)}/download`}
                    download={documentFileName(document)}
                    aria-label={`Download ${document.title}`}
                    className="grid h-6 w-6 shrink-0 place-items-center rounded text-muted transition hover:bg-white/10 hover:text-white"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </a>
                </div>
              )) : (
                <p className="text-[10px] leading-4 text-muted">Save an Assistant response as an editable cover-letter DOCX.</p>
              )}
            </div>
          </div>

          <div className="p-3.5 2xl:p-4">
            <p className="text-xs font-bold text-white">How Rufina uses context</p>
            <p className="mt-2 text-[11px] leading-5 text-muted">Answers are grounded in the selected data. Missing evidence is called out instead of being invented.</p>
            {selectedJob?.skills.length ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {selectedJob.skills.slice(0, 6).map((skill) => <span key={skill} className="rounded-md border border-border bg-white/[0.035] px-2 py-1 text-[10px] text-[#cfd5df]">{skill}</span>)}
              </div>
            ) : null}
          </div>
        </aside>
      </div>
    </section>
    {documentDraft && (
      <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm">
        <div role="dialog" aria-modal="true" aria-label="Document editor" className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-border bg-[#111821] shadow-2xl">
          <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-accent">Document artifact</p>
              <h2 className="mt-1 text-lg font-bold text-white">{documentDraft.id ? "Edit document" : "Create document"}</h2>
            </div>
            <button type="button" onClick={() => setDocumentDraft(null)} aria-label="Close document editor" className="rounded-md p-1.5 text-muted hover:bg-white/10 hover:text-white">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="job-scroll grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_240px]">
            <div className="space-y-3 p-4">
              <div className="grid gap-3 sm:grid-cols-[170px_minmax(0,1fr)]">
                <label className="space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wide text-muted">Type</span>
                  <select
                    value={documentDraft.type}
                    disabled={Boolean(documentDraft.id)}
                    onChange={(event) => setDocumentDraft((draft) => draft ? { ...draft, type: event.target.value as "cover_letter" } : draft)}
                    className="h-9 w-full rounded-md border border-border bg-[#151c24] px-2.5 text-xs text-white outline-none focus:border-accent/60 disabled:opacity-60"
                  >
                    <option value="cover_letter">Cover letter</option>
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wide text-muted">Title</span>
                  <input
                    value={documentDraft.title}
                    onChange={(event) => setDocumentDraft((draft) => draft ? { ...draft, title: event.target.value } : draft)}
                    className="h-9 w-full rounded-md border border-border bg-[#151c24] px-2.5 text-xs text-white outline-none focus:border-accent/60"
                  />
                </label>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wide text-muted">Vacancy version</span>
                  <select
                    value={documentDraft.jobId}
                    onChange={(event) => setDocumentDraft((draft) => draft ? { ...draft, jobId: event.target.value } : draft)}
                    className="h-9 w-full rounded-md border border-border bg-[#151c24] px-2.5 text-xs text-white outline-none focus:border-accent/60"
                  >
                    <option value="">General version</option>
                    {jobs.map((job) => <option key={job.id} value={job.id}>{job.title} · {job.company}</option>)}
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wide text-muted">Attach to application</span>
                  <select
                    value={documentDraft.applicationId}
                    onChange={(event) => setDocumentDraft((draft) => draft ? { ...draft, applicationId: event.target.value } : draft)}
                    className="h-9 w-full rounded-md border border-border bg-[#151c24] px-2.5 text-xs text-white outline-none focus:border-accent/60"
                  >
                    <option value="">Do not attach</option>
                    {applications.map((application) => <option key={application.id} value={application.id}>{application.job.title} · {application.job.company}</option>)}
                  </select>
                </label>
              </div>

              <label className="block space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wide text-muted">Content</span>
                <textarea
                  value={documentDraft.content}
                  onChange={(event) => setDocumentDraft((draft) => draft ? { ...draft, content: event.target.value } : draft)}
                  rows={18}
                  className="min-h-[360px] w-full resize-y rounded-md border border-border bg-[#0c1219] p-3 font-mono text-xs leading-5 text-[#e5e9f0] outline-none focus:border-accent/60"
                />
              </label>
              {documentError ? <p className="text-xs text-red-300">{documentError}</p> : null}
            </div>

            <aside className="border-t border-border p-4 lg:border-l lg:border-t-0">
              <div className="flex items-center gap-2 text-xs font-bold text-white">
                <History className="h-4 w-4 text-accent" /> Versions
              </div>
              {documentDraft.id ? (
                <div className="mt-3 space-y-2">
                  {(documents.find((document) => document.id === documentDraft.id)?.versions ?? [])
                    .slice()
                    .reverse()
                    .map((version) => (
                      <div key={version.id} className="rounded-md border border-border bg-white/[0.025] p-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10px] font-bold text-white">Version {version.version}</span>
                          {version.version === documents.find((document) => document.id === documentDraft.id)?.currentVersion ? (
                            <span className="text-[8px] font-bold uppercase text-success">Current</span>
                          ) : (
                            <button type="button" disabled={isDocumentSaving} onClick={() => restoreDocumentVersion(documentDraft.id, version.version)} className="text-[9px] font-bold text-accent hover:text-white">Restore</button>
                          )}
                        </div>
                        <p className="mt-1 text-[9px] text-muted">{formatThreadDate(version.createdAt)}</p>
                        <a href={`${apiBaseUrl}/documents/${encodeURIComponent(documentDraft.id)}/download?version=${version.version}`} className="mt-2 inline-flex items-center gap-1 text-[9px] font-semibold text-muted hover:text-white">
                          <Download className="h-3 w-3" /> Download
                        </a>
                      </div>
                    ))}
                </div>
              ) : (
                <p className="mt-3 text-[10px] leading-4 text-muted">The first version is created when you save. Every content edit creates the next version.</p>
              )}
            </aside>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-3">
            <div>
              {documentDraft.id ? (
                <Button variant="ghost" onClick={() => deleteDocumentArtifact(documentDraft.id)} className="h-8 px-2 text-[10px] text-red-300 hover:bg-red-500/10 hover:text-red-200">
                  <Trash2 className="h-3.5 w-3.5" /> Delete document
                </Button>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              {documentDraft.id ? (
                <a href={`${apiBaseUrl}/documents/${encodeURIComponent(documentDraft.id)}/download`} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-[10px] font-bold text-muted hover:bg-white/10 hover:text-white">
                  <Download className="h-3.5 w-3.5" /> Download DOCX
                </a>
              ) : null}
              <Button onClick={saveDocumentArtifact} disabled={isDocumentSaving || !documentDraft.title.trim() || !documentDraft.content.trim()} className="h-8 rounded-md bg-accent px-3 text-[10px] font-bold text-white hover:bg-[#ff6b12] disabled:opacity-40">
                {documentDraft.applicationId ? <Paperclip className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
                {isDocumentSaving ? "Saving…" : documentDraft.applicationId ? "Save & attach" : "Save version"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    )}
    {pendingConsentPrompt ? (
      <div className="fixed inset-0 z-[60] grid place-items-center bg-black/75 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="assistant-ai-consent-title">
        <div className="w-full max-w-lg rounded-xl border border-border bg-[#111821] p-5 shadow-2xl">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-accent/25 bg-accent/10 text-accent"><ShieldCheck className="h-5 w-5" /></span>
            <div><p className="text-[10px] font-black uppercase tracking-[0.12em] text-accent">AI data disclosure · {aiPrivacy.currentConsentVersion}</p><h2 id="assistant-ai-consent-title" className="mt-1 text-lg font-bold text-white">Send selected context to {aiPrivacy.providerName}</h2></div>
          </div>
          <p className="mt-4 text-xs leading-5 text-[#cbd3df]">Rufina sends your message and selected profile, vacancy, or application context using {aiPrivacy.providerName}. AI results are deleted after your selected retention period.</p>
          <label className="mt-4 block text-xs font-semibold text-[#dce2ea]">Keep AI results for (days)
            <input type="number" min={1} max={365} value={aiPrivacy.retentionDays} onChange={(event) => setAiPrivacy((privacy) => ({ ...privacy, retentionDays: Math.min(365, Math.max(1, Number(event.target.value) || 1)) }))} className="mt-2 h-10 w-full rounded-lg border border-border bg-[#0b1119] px-3 text-xs text-white" />
          </label>
          <label className="mt-4 flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-white/[0.025] p-3 text-xs leading-5 text-[#dce2ea]"><input type="checkbox" checked={aiConsentConfirmed} onChange={(event) => setAiConsentConfirmed(event.target.checked)} className="mt-1 h-4 w-4 accent-[#ff5a00]" /><span>I understand and agree to send this context to the AI provider.</span></label>
          <div className="mt-5 flex justify-end gap-2"><Button variant="ghost" onClick={() => setPendingConsentPrompt(null)} className="h-9 border border-border px-3 text-xs">Cancel</Button><Button disabled={!aiConsentConfirmed || isSavingAiConsent} onClick={() => void grantAiConsent()} className="h-9 bg-accent px-3 text-xs font-bold text-white disabled:opacity-40">{isSavingAiConsent ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />} Continue to AI</Button></div>
        </div>
      </div>
    ) : null}
    </>
  );
}
