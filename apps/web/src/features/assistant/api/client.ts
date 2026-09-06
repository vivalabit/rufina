import { apiClient } from "@/shared/api/client";

import {
  encodeAssistantMessage,
  normalizeAssistantAppliedAction,
  normalizeAssistantDocuments,
  normalizeAssistantThreads,
} from "./dto";
import type {
  AssistantActionPreview,
  AssistantAppliedAction,
  AssistantContextKind,
  AssistantDocument,
  AssistantMessage,
  AssistantSseEvent,
  AssistantThread,
} from "../model/types";

export async function fetchAssistantThreads(archived: boolean, signal?: AbortSignal) {
  return (await apiClient.json<AssistantThread[]>({
    path: "/assistant/conversations",
    query: { archived },
    signal,
    errorMessage: "Conversation loading failed",
  }, normalizeAssistantThreads)).data;
}

export async function persistAssistantMessage(
  threadId: string,
  message: AssistantMessage,
  signal?: AbortSignal,
) {
  await apiClient.empty({
    path: `/assistant/conversations/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(message.id)}`,
    method: "PUT",
    json: {
      ...message,
      content: encodeAssistantMessage(message),
      actions: undefined,
    },
    signal,
    errorMessage: "Message persistence failed",
  });
}

export async function fetchAssistantDocuments(signal?: AbortSignal) {
  return (await apiClient.json<AssistantDocument[]>({
    path: "/documents",
    signal,
    errorMessage: "Documents are temporarily unavailable",
  }, normalizeAssistantDocuments)).data;
}

export async function patchAssistantThread(
  threadId: string,
  patch: { contextKind?: AssistantContextKind; contextId?: string; archived?: boolean },
  signal?: AbortSignal,
) {
  await apiClient.empty({
    path: `/assistant/conversations/${encodeURIComponent(threadId)}`,
    method: "PATCH",
    json: patch,
    signal,
    errorMessage: "Conversation update failed",
  });
}

export async function deleteAssistantThread(threadId: string, signal?: AbortSignal) {
  await apiClient.empty({
    path: `/assistant/conversations/${encodeURIComponent(threadId)}`,
    method: "DELETE",
    signal,
    errorMessage: "Conversation deletion failed",
  });
}

export async function saveAssistantDocument(
  documentId: string | null,
  payload: unknown,
  signal?: AbortSignal,
) {
  return (await apiClient.json<AssistantDocument>({
    path: documentId ? `/documents/${encodeURIComponent(documentId)}` : "/documents",
    method: documentId ? "PATCH" : "POST",
    json: payload,
    signal,
    errorMessage: "Document save failed",
  })).data;
}

export async function attachAssistantDocument(
  documentId: string,
  applicationId: string,
  signal?: AbortSignal,
) {
  return (await apiClient.json<AssistantDocument>({
    path: `/documents/${encodeURIComponent(documentId)}/attachments`,
    method: "POST",
    json: { applicationId },
    signal,
    errorMessage: "Document attachment failed",
  })).data;
}

export async function restoreAssistantDocumentVersion(
  documentId: string,
  version: number,
  signal?: AbortSignal,
) {
  return (await apiClient.json<AssistantDocument>({
    path: `/documents/${encodeURIComponent(documentId)}/restore`,
    method: "POST",
    json: { version },
    signal,
    errorMessage: "Version restore failed",
  })).data;
}

export async function deleteAssistantDocument(documentId: string, signal?: AbortSignal) {
  await apiClient.empty({
    path: `/documents/${encodeURIComponent(documentId)}`,
    method: "DELETE",
    signal,
    errorMessage: "Document deletion failed",
  });
}

export async function applyAssistantAction(
  action: AssistantActionPreview,
  signal?: AbortSignal,
): Promise<AssistantAppliedAction> {
  return (await apiClient.json<AssistantAppliedAction>({
    path: "/assistant/actions/apply",
    method: "POST",
    json: {
      action: { ...action, status: "preview", resultMessage: "" },
    },
    signal,
    errorMessage: "Action could not be applied",
  }, normalizeAssistantAppliedAction)).data;
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
    return data && typeof data === "object"
      ? { event, data: data as Record<string, unknown> }
      : null;
  } catch {
    return null;
  }
}

async function consumeAssistantSse(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: AssistantSseEvent) => void,
): Promise<"done" | "stopped" | "error" | null> {
  const reader = stream.getReader();
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

export async function streamAssistantMessage(
  payload: Record<string, unknown>,
  signal: AbortSignal,
  onEvent: (event: AssistantSseEvent) => void,
) {
  const result = await apiClient.stream({
    path: "/assistant/chat/stream",
    method: "POST",
    headers: { Accept: "text/event-stream" },
    json: payload,
    signal,
    timeoutMs: null,
    errorMessage: "Assistant request failed. Please try again.",
  });
  return await consumeAssistantSse(result.data, onEvent);
}

export async function stopAssistantStream(requestId: string, signal?: AbortSignal) {
  await apiClient.empty({
    path: `/assistant/chat/stream/${encodeURIComponent(requestId)}`,
    method: "DELETE",
    signal,
    errorMessage: "Assistant stream could not be stopped",
  });
}

export async function deleteAssistantMessage(
  threadId: string,
  messageId: string,
  signal?: AbortSignal,
) {
  await apiClient.empty({
    path: `/assistant/conversations/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}`,
    method: "DELETE",
    signal,
    errorMessage: "Message deletion failed",
  });
}

export function assistantDocumentDownloadUrl(documentId: string, version?: number) {
  return apiClient.url(
    `/documents/${encodeURIComponent(documentId)}/download`,
    version === undefined ? undefined : { version },
  ).toString();
}
