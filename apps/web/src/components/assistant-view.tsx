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
import {
  applyAssistantAction as applyAssistantActionRequest,
  assistantDocumentDownloadUrl,
  attachAssistantDocument,
  deleteAssistantDocument,
  deleteAssistantMessage,
  deleteAssistantThread,
  fetchAssistantDocuments,
  fetchAssistantThreads,
  importLegacyAssistantThread,
  patchAssistantThread,
  persistAssistantMessage,
  restoreAssistantDocumentVersion,
  saveAssistantDocument,
  stopAssistantStream,
  streamAssistantMessage,
} from "@/features/assistant/api/client";
import {
  normalizeAssistantActions,
  normalizeAssistantDocuments,
  normalizeAssistantThreads,
} from "@/features/assistant/api/dto";
import type {
  AssistantActionPreview,
  AssistantAppliedAction,
  AssistantContextKind,
  AssistantDocument,
  AssistantDocumentAttachment,
  AssistantDocumentDraft,
  AssistantLaunch,
  AssistantMessage,
  AssistantThread,
} from "@/features/assistant/model/types";
import { getAiSourceLabel } from "@/lib/ai-source";
import { cn } from "@/lib/utils";

export type {
  AssistantAppliedAction,
  AssistantDocumentAttachment,
  AssistantLaunch,
} from "@/features/assistant/model/types";

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

type AssistantConnectionStatus = "idle" | "connecting" | "connected" | "disconnected";

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
const assistantMessageMaxChars = 6_000;

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
    return date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
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
  const [, setConnectionStatus] = useState<AssistantConnectionStatus>("idle");
  const [streamingMessageId, setStreamingMessageId] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState("");
  const [isLoaded, setIsLoaded] = useState(false);
  const [documents, setDocuments] = useState<AssistantDocument[]>([]);
  const [documentDraft, setDocumentDraft] = useState<AssistantDocumentDraft | null>(null);
  const [isDocumentSaving, setIsDocumentSaving] = useState(false);
  const [documentError, setDocumentError] = useState("");
  const [assistantError, setAssistantError] = useState("");
  const [pendingAutoSubmitLaunch, setPendingAutoSubmitLaunch] =
    useState<AssistantLaunch | null>(null);
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
          const legacyThreads = normalizeAssistantThreads(rawThreads ? JSON.parse(rawThreads) : []);
          if (legacyThreads.length) {
            const archivedThreads = await fetchAssistantThreads(true);
            const serverIds = new Set(
              [...serverThreads, ...archivedThreads].map((thread) => thread.id),
            );
            const threadsToImport = legacyThreads.filter((thread) => !serverIds.has(thread.id));
            await Promise.all(
              threadsToImport.map((thread) => importLegacyAssistantThread(thread)),
            );
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
    fetchAssistantDocuments()
      .then((loadedDocuments) => {
        if (!cancelled) setDocuments(loadedDocuments);
      })
      .catch(() => {
        if (!cancelled) setDocumentError("Documents are temporarily unavailable");
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
    void patchAssistantThread(activeThread.id, {
      contextKind: nextKind,
      contextId: nextId,
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
      await deleteAssistantThread(threadId);
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
      await patchAssistantThread(threadId, { archived });
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

  async function saveDocumentArtifact() {
    if (!documentDraft?.title.trim() || !documentDraft.content.trim()) return;
    setIsDocumentSaving(true);
    setDocumentError("");
    try {
      const isExisting = Boolean(documentDraft.id);
      let savedDocument = await saveAssistantDocument(
        isExisting ? documentDraft.id : null,
        {
          ...(isExisting ? {} : { type: documentDraft.type }),
          title: documentDraft.title.trim(),
          content: documentDraft.content.trim(),
          jobId: documentDraft.jobId || null,
          ...(!isExisting && documentDraft.applicationId
            ? { applicationId: documentDraft.applicationId }
            : {}),
        },
      );

      if (
        isExisting &&
        documentDraft.applicationId &&
        !savedDocument.applicationIds.includes(documentDraft.applicationId)
      ) {
        savedDocument = await attachAssistantDocument(
          savedDocument.id,
          documentDraft.applicationId,
        );
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
          downloadUrl: assistantDocumentDownloadUrl(savedDocument.id),
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
      const restored = await restoreAssistantDocumentVersion(documentId, version);
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
      await deleteAssistantDocument(documentId);
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
      const result = await applyAssistantActionRequest(action);
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
              downloadUrl: assistantDocumentDownloadUrl(savedDocument.id),
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

  async function submitMessage(explicitPrompt?: string) {
    const prompt = (explicitPrompt ?? draft).trim();
    if (!prompt || isGenerating) return;
    if (prompt.length > assistantMessageMaxChars) {
      setAssistantError(`Message is too long. The limit is ${assistantMessageMaxChars.toLocaleString()} characters.`);
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
      const terminalEvent = await streamAssistantMessage(
        { ...requestPayload, offset: 0 },
        abortController.signal,
        ({ event, data }) => {
          if (event === "connected") {
            setConnectionStatus("connected");
            return;
          }
          if (event === "delta" && typeof data.text === "string") {
            streamedContent += data.text;
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
        },
      );

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

  async function stopGenerating() {
    const requestId = activeRequestIdRef.current;
    if (!requestId || !isGenerating) return;
    stopRequestedRef.current = true;
    streamAbortControllerRef.current?.abort();
    setConnectionStatus("idle");
    try {
      await stopAssistantStream(requestId);
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
    void deleteAssistantMessage(activeThread.id, messageId)
      .catch(() => setConnectionStatus("disconnected"));
    setDraft(previousUserMessage.content);
  }

  async function copyMessage(message: AssistantMessage) {
    await navigator.clipboard?.writeText(message.content);
    setCopiedMessageId(message.id);
    window.setTimeout(() => setCopiedMessageId(""), 1400);
  }

  return (
    <>
    <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-3 py-3 sm:px-4 xl:px-4 2xl:px-5 2xl:py-4">
      <header className="mb-3 flex shrink-0 items-start justify-between gap-3 2xl:mb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-[#e95300] to-[#df4f00] text-foreground shadow-[0_10px_28px_rgba(255,90,0,0.28)]">
              <Sparkles className="h-[18px] w-[18px]" />
            </span>
            <h1 className="page-title text-[24px] leading-tight text-foreground sm:text-[27px] 2xl:text-[31px]">AI Assistant</h1>
          </div>
        </div>
        <Button onClick={startNewChat} disabled={isGenerating} className="h-9 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-3 text-xs 2xl:h-10 2xl:text-sm">
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
                className="flex items-center gap-1 rounded px-1.5 py-1 text-[9px] font-bold uppercase tracking-wide text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
              >
                {showArchived ? <ArchiveRestore className="h-3 w-3" /> : <Archive className="h-3 w-3" />}
                {showArchived ? "Active" : "Archive"}
              </button>
            </div>
            <label className="mt-2.5 flex h-9 items-center gap-2 rounded-md border border-border bg-[#fff8f1] px-2.5 focus-within:border-accent/60">
              <Search className="h-3.5 w-3.5 text-muted" />
              <input value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="Search history" className="assistant-history-search-input min-w-0 flex-1 appearance-none border-0 !bg-transparent text-xs text-foreground outline-none placeholder:text-muted focus-visible:outline-none focus-visible:outline-offset-0" />
            </label>
          </div>
          <div className="job-scroll min-h-0 flex-1 overflow-y-auto p-2">
            {filteredThreads.length ? filteredThreads.map((thread) => (
              <div key={thread.id} className={cn("group relative mb-1 rounded-md border transition", thread.id === activeThreadId ? "border-accent/35 bg-accent/10" : "border-transparent hover:border-border hover:bg-[#fff3e8]")}>
                <button type="button" onClick={() => setActiveThreadId(thread.id)} className="w-full p-2.5 pr-14 text-left">
                  <p className="line-clamp-2 text-xs font-bold leading-4 text-[#1d1e1c]">{thread.title}</p>
                  <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-muted">
                    <span className="truncate">{getContextLabel(thread.contextKind, thread.contextId, jobs, applications)}</span>
                    <span className="shrink-0">{formatThreadDate(thread.updatedAt)}</span>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setThreadArchived(thread.id, !showArchived)}
                  aria-label={showArchived ? "Restore conversation" : "Archive conversation"}
                  className="absolute right-7 top-2 rounded p-1 text-muted opacity-0 transition hover:bg-[#fff3e8] hover:text-foreground group-hover:opacity-100"
                >
                  {showArchived ? <ArchiveRestore className="h-3.5 w-3.5" /> : <Archive className="h-3.5 w-3.5" />}
                </button>
                <button type="button" onClick={() => deleteThread(thread.id)} aria-label="Delete conversation" className="absolute right-1.5 top-2 rounded p-1 text-muted opacity-0 transition hover:bg-[#fff3e8] hover:text-foreground group-hover:opacity-100">
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
                className="h-8 appearance-none rounded-md border border-border bg-[#ffffff] pl-2.5 pr-7 text-xs font-bold text-foreground outline-none focus:border-accent/60"
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
                  className="h-8 w-full appearance-none truncate rounded-md border border-border bg-[#ffffff] pl-2.5 pr-7 text-xs font-semibold text-[#1d1e1c] outline-none focus:border-accent/60"
                >
                  {contextKind === "job" ? jobs.map((job) => <option key={job.id} value={job.id}>{job.title} · {job.company}</option>) : applications.map((application) => <option key={application.id} value={application.id}>{application.job.title} · {application.job.company}</option>)}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-2 h-4 w-4 text-muted" />
              </div>
            )}
          </div>

          <div className="job-scroll min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-5 2xl:px-7 2xl:py-6">
            {!activeThread?.messages.length ? (
              <div className="mx-auto flex min-h-full max-w-[720px] flex-col justify-center py-4">
                <div className="text-center">
                  <span className="mx-auto grid h-12 w-12 place-items-center rounded-xl border border-accent/30 bg-accent/10 text-accent">
                    <Bot className="h-6 w-6" />
                  </span>
                  <h2 className="mt-3 text-xl font-bold text-foreground 2xl:text-2xl">What are we working on?</h2>
                  <p className="mx-auto mt-1.5 max-w-[540px] text-xs leading-5 text-muted 2xl:text-sm">I use your selected profile, vacancy, or application to make every answer specific and evidence-based.</p>
                </div>
                <div className="mt-5 grid gap-2 sm:grid-cols-2 2xl:mt-6 2xl:gap-3">
                  {quickActions.map((action) => (
                    <button key={action.title} type="button" disabled={showArchived} onClick={() => submitMessage(action.prompt)} className="group rounded-lg border border-border bg-[#fff8f1] p-3 text-left transition hover:border-accent/40 hover:bg-accent/[0.07] disabled:cursor-not-allowed disabled:opacity-40 2xl:p-4">
                      <span className="grid h-8 w-8 place-items-center rounded-md bg-accent/12 text-accent transition group-hover:bg-accent/20"><action.icon className="h-4 w-4" /></span>
                      <p className="mt-2.5 text-sm font-bold text-foreground">{action.title}</p>
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
                    <div className={cn("min-w-0 max-w-[88%]", message.role === "user" && "rounded-xl rounded-tr-sm border border-accent/20 bg-[#fff3e8] px-3.5 py-2.5 text-foreground shadow-[4px_5px_18px_rgba(227,214,197,0.55)]")}>
                      {message.role === "assistant" && (
                        <p className="mb-1.5 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.1em] text-accent">
                          Rufina Assistant
                          {message.source && (
                            <span className="rounded border border-border bg-[#fff8f1] px-1.5 py-0.5 text-[8px] tracking-[0.08em] text-muted">
                              {getAiSourceLabel(message.source)}
                            </span>
                          )}
                        </p>
                      )}
                      <p className={cn("whitespace-pre-wrap text-[13px] leading-5 2xl:text-sm 2xl:leading-6", message.role === "assistant" ? "text-[#1d1e1c]" : "text-foreground")}>
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
                                      <p className="text-xs font-bold text-foreground">{action.title}</p>
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
                                      <p className="mt-1 max-h-36 overflow-y-auto whitespace-pre-wrap text-[10px] leading-4 text-[#1d1e1c]">{field.after || "Empty"}</p>
                                    </div>
                                  ))}
                                </div>
                                <div className="mt-2.5 flex items-center justify-between gap-2">
                                  <p className={cn(
                                    "min-w-0 text-[9px] leading-4",
                                    action.status === "error" ? "text-accent" : isApplied ? "text-success" : "text-muted",
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
                                      className="h-8 shrink-0 rounded-md bg-accent px-3 text-[10px] font-bold text-foreground hover:bg-[#e95300] disabled:opacity-50"
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
                          <Button variant="ghost" size="sm" onClick={() => copyMessage(message)} className="h-7 px-2 text-[10px] text-muted hover:text-foreground">
                            {copiedMessageId === message.id ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />} {copiedMessageId === message.id ? "Copied" : "Copy"}
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => regenerateMessage(message.id)} className="h-7 px-2 text-[10px] text-muted hover:text-foreground">
                            <RefreshCw className="h-3.5 w-3.5" /> Regenerate
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => openDocumentFromMessage(message)} className="h-7 px-2 text-[10px] text-muted hover:text-foreground">
                            <Save className="h-3.5 w-3.5" /> Save as cover letter
                          </Button>
                        </div>
                      )}
                    </div>
                    {message.role === "user" && <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#fff8f1] text-[#1d1e1c]"><UserRound className="h-4 w-4" /></span>}
                  </article>
                ))}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-border p-3 2xl:p-4">
            {assistantError ? (
              <div className="mx-auto mb-2 flex max-w-[780px] items-start gap-2 rounded-md border border-accent/25 bg-accent/10 px-3 py-2 text-[11px] leading-4 text-accent">
                <span className="min-w-0 flex-1">{assistantError}</span>
                <button type="button" onClick={() => setAssistantError("")} aria-label="Dismiss assistant error" className="shrink-0 text-accent hover:text-foreground">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : null}
            <div className="mx-auto max-w-[780px] rounded-lg border border-border bg-[#fff8f1] p-2 shadow-[0_12px_34px_rgba(0,0,0,0.18)] focus-within:border-accent/60">
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
                className="max-h-32 min-h-[42px] w-full resize-none appearance-none border-0 !bg-transparent px-2 py-1 text-[13px] leading-5 text-foreground outline-none placeholder:text-muted focus-visible:outline-none focus-visible:outline-offset-0 2xl:text-sm"
              />
              <div className="flex items-center justify-between gap-2 px-1">
                <p className="truncate text-[10px] text-muted">
                  Using: {contextLabel}
                  {draft.length >= assistantMessageMaxChars * 0.8 ? ` · ${draft.length.toLocaleString()}/${assistantMessageMaxChars.toLocaleString()}` : ""}
                </p>
                {isGenerating ? (
                  <Button onClick={stopGenerating} aria-label="Stop generating" className="h-8 rounded-md border border-accent/25 bg-accent/10 px-2.5 text-[10px] font-bold text-accent hover:bg-accent/10">
                    <Square className="h-3 w-3 fill-current" /> Stop generating
                  </Button>
                ) : (
                  <Button onClick={() => submitMessage()} disabled={showArchived || !draft.trim()} aria-label="Send message" className="h-8 w-8 rounded-md bg-accent p-0 text-foreground hover:bg-[#e95300] disabled:opacity-40">
                    <Send className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
            <p className="mt-1.5 text-center text-[9px] text-muted">Rufina may make mistakes. Verify generated claims before using them.</p>
          </div>
        </main>

        <aside className="panel job-scroll hidden min-h-0 overflow-y-auto xl:block">
          <div className="border-b border-border p-3.5 2xl:p-4">
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted 2xl:text-xs">Active context</p>
            <div className="mt-3 flex min-h-[72px] items-center gap-2.5 rounded-lg border border-accent/35 bg-accent/[0.065] p-3 2xl:min-h-[78px] 2xl:gap-3 2xl:p-3.5">
              <span className="grid h-8 w-8 shrink-0 place-items-center text-accent 2xl:h-9 2xl:w-9">
                {contextKind === "profile" ? <UserRound className="h-5 w-5 2xl:h-6 2xl:w-6" /> : contextKind === "job" ? <BriefcaseBusiness className="h-5 w-5 2xl:h-6 2xl:w-6" /> : <FileText className="h-5 w-5 2xl:h-6 2xl:w-6" />}
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-bold leading-5 text-foreground 2xl:text-[15px]">{contextLabel}</p>
                {selectedJob && <p className="mt-0.5 text-[10px] text-muted 2xl:text-[11px]">{selectedJob.location} · {selectedJob.match}% match</p>}
                {selectedApplication && <span className="mt-2 inline-flex rounded-md border border-border bg-white px-2 py-1 text-[10px] font-bold capitalize text-[#1d1e1c]">{selectedApplication.status}</span>}
              </div>
            </div>
          </div>

          <div className="border-b border-border p-3.5 2xl:p-4">
            <p className="text-sm font-bold text-foreground 2xl:text-[15px]">Sources available</p>
            <div className="mt-2 divide-y divide-border/70">
              {[
                { label: "Candidate profile", ready: Boolean(profile.name || profile.current_role || profile.skills) },
                { label: "Resume", ready: Boolean(profile.resume_file_name) },
                { label: "Vacancy details", ready: Boolean(selectedJob) },
                { label: "Application notes", ready: Boolean(selectedApplication?.notes) },
              ].map((source) => (
                <div key={source.label} className="flex min-h-[44px] items-center gap-2.5 py-2.5 2xl:min-h-[48px] 2xl:gap-3">
                  <span className={cn("grid h-5 w-5 shrink-0 place-items-center rounded-full border", source.ready ? "border-accent/40 text-accent" : "border-[#dedede] text-[#999999]")}>
                    {source.ready ? <Check className="h-3 w-3" strokeWidth={2.4} /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                  </span>
                  <span className={cn("min-w-0 flex-1 text-xs 2xl:text-[13px]", source.ready ? "text-[#1d1e1c]" : "text-muted")}>{source.label}</span>
                  <span className={cn("shrink-0 text-[9px] font-bold uppercase tracking-[0.04em] 2xl:text-[10px]", source.ready ? "text-[#18a52b]" : "text-[#8e8b87]")}>{source.ready ? "Ready" : "Missing"}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="p-3.5 2xl:p-4">
            <p className="text-xs font-bold text-foreground 2xl:text-sm">How Rufina uses context</p>
            <p className="mt-1.5 text-[11px] leading-4 text-muted 2xl:text-xs 2xl:leading-5">Answers are grounded in the selected data. Missing evidence is called out instead of being invented.</p>
            {selectedJob?.skills.length ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {selectedJob.skills.slice(0, 6).map((skill) => <span key={skill} className="rounded-md border border-border bg-[#fff8f1] px-2 py-1 text-[10px] text-[#4a4a47]">{skill}</span>)}
              </div>
            ) : null}
          </div>
        </aside>
      </div>
    </section>
    {documentDraft && (
      <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm">
        <div role="dialog" aria-modal="true" aria-label="Document editor" className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-border bg-[#ffffff] shadow-2xl">
          <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-accent">Document artifact</p>
              <h2 className="mt-1 text-lg font-bold text-foreground">{documentDraft.id ? "Edit document" : "Create document"}</h2>
            </div>
            <button type="button" onClick={() => setDocumentDraft(null)} aria-label="Close document editor" className="rounded-md p-1.5 text-muted hover:bg-[#fff3e8] hover:text-foreground">
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
                    className="h-9 w-full rounded-md border border-border bg-[#ffffff] px-2.5 text-xs text-foreground outline-none focus:border-accent/60 disabled:opacity-60"
                  >
                    <option value="cover_letter">Cover letter</option>
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wide text-muted">Title</span>
                  <input
                    value={documentDraft.title}
                    onChange={(event) => setDocumentDraft((draft) => draft ? { ...draft, title: event.target.value } : draft)}
                    className="h-9 w-full rounded-md border border-border bg-[#ffffff] px-2.5 text-xs text-foreground outline-none focus:border-accent/60"
                  />
                </label>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wide text-muted">Vacancy version</span>
                  <select
                    value={documentDraft.jobId}
                    onChange={(event) => setDocumentDraft((draft) => draft ? { ...draft, jobId: event.target.value } : draft)}
                    className="h-9 w-full rounded-md border border-border bg-[#ffffff] px-2.5 text-xs text-foreground outline-none focus:border-accent/60"
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
                    className="h-9 w-full rounded-md border border-border bg-[#ffffff] px-2.5 text-xs text-foreground outline-none focus:border-accent/60"
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
                  className="min-h-[360px] w-full resize-y rounded-md border border-border bg-white p-3 font-mono text-xs leading-5 text-[#1d1e1c] outline-none focus:border-accent/60"
                />
              </label>
              {documentError ? <p className="text-xs text-accent">{documentError}</p> : null}
            </div>

            <aside className="border-t border-border p-4 lg:border-l lg:border-t-0">
              <div className="flex items-center gap-2 text-xs font-bold text-foreground">
                <History className="h-4 w-4 text-accent" /> Versions
              </div>
              {documentDraft.id ? (
                <div className="mt-3 space-y-2">
                  {(documents.find((document) => document.id === documentDraft.id)?.versions ?? [])
                    .slice()
                    .reverse()
                    .map((version) => (
                      <div key={version.id} className="rounded-md border border-border bg-[#fff8f1] p-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10px] font-bold text-foreground">Version {version.version}</span>
                          {version.version === documents.find((document) => document.id === documentDraft.id)?.currentVersion ? (
                            <span className="text-[8px] font-bold uppercase text-success">Current</span>
                          ) : (
                            <button type="button" disabled={isDocumentSaving} onClick={() => restoreDocumentVersion(documentDraft.id, version.version)} className="text-[9px] font-bold text-accent hover:text-foreground">Restore</button>
                          )}
                        </div>
                        <p className="mt-1 text-[9px] text-muted">{formatThreadDate(version.createdAt)}</p>
                        <a href={assistantDocumentDownloadUrl(documentDraft.id, version.version)} className="mt-2 inline-flex items-center gap-1 text-[9px] font-semibold text-muted hover:text-foreground">
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
                <Button variant="ghost" onClick={() => deleteDocumentArtifact(documentDraft.id)} className="h-8 px-2 text-[10px] text-accent hover:bg-accent/10 hover:text-accent">
                  <Trash2 className="h-3.5 w-3.5" /> Delete document
                </Button>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              {documentDraft.id ? (
                <a href={assistantDocumentDownloadUrl(documentDraft.id)} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-[10px] font-bold text-muted hover:bg-[#fff3e8] hover:text-foreground">
                  <Download className="h-3.5 w-3.5" /> Download DOCX
                </a>
              ) : null}
              <Button onClick={saveDocumentArtifact} disabled={isDocumentSaving || !documentDraft.title.trim() || !documentDraft.content.trim()} className="h-8 rounded-md bg-accent px-3 text-[10px] font-bold text-foreground hover:bg-[#e95300] disabled:opacity-40">
                {documentDraft.applicationId ? <Paperclip className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
                {isDocumentSaving ? "Saving…" : documentDraft.applicationId ? "Save & attach" : "Save version"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    )}
    </>
  );
}
