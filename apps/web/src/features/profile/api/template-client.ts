import {
  apiClient,
  ApiResponseError,
} from "@/shared/api/client";
import type {
  ResumeTemplate,
  ResumeTemplateDraft,
} from "@/lib/resume-templates";

function normalizeTemplates(value: unknown): ResumeTemplate[] {
  return Array.isArray(value) ? value as ResumeTemplate[] : [];
}

export async function fetchResumeTemplates(signal?: AbortSignal) {
  return (await apiClient.json<ResumeTemplate[]>({
    path: "/resume-templates",
    cache: "no-store",
    signal,
    errorMessage: "Could not load resume templates.",
  }, normalizeTemplates)).data;
}

export async function saveResumeTemplate(
  id: string | null,
  draft: ResumeTemplateDraft,
  signal?: AbortSignal,
) {
  return (await apiClient.json<ResumeTemplate>({
    path: id ? `/resume-templates/${encodeURIComponent(id)}` : "/resume-templates",
    method: id ? "PATCH" : "POST",
    json: {
      name: draft.name.trim(),
      baseTemplateId: draft.baseTemplateId,
      designJson: draft.designJson,
    },
    signal,
    errorMessage: "Could not save the template.",
  })).data;
}

export async function duplicateResumeTemplate(id: string, signal?: AbortSignal) {
  return (await apiClient.json<ResumeTemplate>({
    path: `/resume-templates/${encodeURIComponent(id)}/duplicate`,
    method: "POST",
    json: {},
    signal,
    errorMessage: "Could not duplicate the template.",
  })).data;
}

export async function deleteResumeTemplate(id: string, signal?: AbortSignal) {
  await apiClient.empty({
    path: `/resume-templates/${encodeURIComponent(id)}`,
    method: "DELETE",
    signal,
    errorMessage: "Could not delete the template.",
  });
}

export async function exportResumeTemplate(id: string, signal?: AbortSignal) {
  const result = await apiClient.blob({
    path: `/resume-templates/${encodeURIComponent(id)}/export`,
    cache: "no-store",
    signal,
    errorMessage: "Could not export the template.",
  });
  const disposition = result.meta.headers.get("Content-Disposition");
  const match = disposition?.match(/filename="?([^";]+)"?/i);
  return { blob: result.data, fileName: match?.[1] ?? null };
}

export async function importResumeTemplate(backup: unknown, signal?: AbortSignal) {
  return (await apiClient.json<ResumeTemplate>({
    path: "/resume-templates/import",
    method: "POST",
    json: backup,
    signal,
    errorMessage: "Could not import the template.",
  })).data;
}

export async function previewResumeTemplate(
  draft: Pick<ResumeTemplateDraft, "baseTemplateId" | "designJson">,
  signal?: AbortSignal,
) {
  try {
    return (await apiClient.blob({
      path: "/resume-templates/preview",
      method: "POST",
      cache: "no-store",
      json: draft,
      signal,
      timeoutMs: 90_000,
      errorMessage: "Could not generate the preview.",
    })).data;
  } catch (error) {
    if (error instanceof ApiResponseError && error.status === 429) {
      throw new Error("Preview limit reached. Wait a moment, then try again.", {
        cause: error,
      });
    }
    throw error;
  }
}
