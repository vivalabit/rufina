import type {
  AssistantActionFieldPreview,
  AssistantActionPreview,
  AssistantAppliedAction,
  AssistantContextKind,
  AssistantDocument,
  AssistantMessage,
  AssistantThread,
} from "../model/types";

const assistantActionMarkerPattern = /\s*<!--TASKO_ACTIONS:([A-Za-z0-9_\-=]+)-->\s*$/;

export function normalizeAssistantActions(value: unknown): AssistantActionPreview[] {
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
    const binary = globalThis.atob(base64);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const actions = normalizeAssistantActions(JSON.parse(new TextDecoder().decode(bytes)));
    return { content: content.replace(assistantActionMarkerPattern, "").trimEnd(), actions };
  } catch {
    return { content, actions: [] as AssistantActionPreview[] };
  }
}

export function encodeAssistantMessage(message: AssistantMessage) {
  if (!message.actions?.length) return message.content;
  const bytes = new TextEncoder().encode(JSON.stringify(message.actions));
  let binary = "";
  const chunkSize = 8_192;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.slice(offset, offset + chunkSize));
  }
  const encoded = globalThis.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_");
  return `${message.content.trimEnd()}\n\n<!--TASKO_ACTIONS:${encoded}-->`;
}

export function normalizeAssistantThreads(value: unknown): AssistantThread[] {
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

export function normalizeAssistantDocuments(value: unknown): AssistantDocument[] {
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

export function normalizeAssistantAppliedAction(value: unknown): AssistantAppliedAction {
  if (!value || typeof value !== "object") {
    throw new Error("Action could not be applied");
  }
  const candidate = value as Partial<AssistantAppliedAction>;
  if (
    typeof candidate.actionId !== "string" ||
    typeof candidate.message !== "string" ||
    candidate.status !== "applied" ||
    !["application", "event", "document", "profile"].includes(candidate.resourceKind ?? "") ||
    !candidate.resource ||
    typeof candidate.resource !== "object"
  ) {
    throw new Error("Action could not be applied");
  }
  return candidate as AssistantAppliedAction;
}
