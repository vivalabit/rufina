"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, FileText, LoaderCircle, RefreshCw } from "lucide-react";

import type { ResumeTemplateDraft } from "@/components/resume-template-editor";
import { apiUnavailableMessage, fetchWithTimeout } from "@/lib/api-client";

const PREVIEW_DEBOUNCE_MS = 650;
const PREVIEW_TIMEOUT_MS = 90_000;

type PreviewStatus = "waiting" | "loading" | "ready" | "error";

export function ResumeTemplatePreview({
  apiBaseUrl,
  draft,
  debounceMs = PREVIEW_DEBOUNCE_MS,
}: {
  apiBaseUrl: string;
  draft: ResumeTemplateDraft;
  debounceMs?: number;
}) {
  const [status, setStatus] = useState<PreviewStatus>("waiting");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [message, setMessage] = useState(
    "Adjust a design setting to generate a preview.",
  );
  const objectUrlRef = useRef<string | null>(null);
  const previewKey = useMemo(
    () =>
      JSON.stringify({
        baseTemplateId: draft.baseTemplateId,
        designJson: draft.designJson,
      }),
    [draft.baseTemplateId, draft.designJson],
  );

  useEffect(() => {
    const controller = new AbortController();
    if (!/^#[0-9A-Fa-f]{6}$/.test(draft.designJson.accentColor)) {
      setStatus("error");
      setMessage("Enter a valid six-digit accent color to update the preview.");
      return () => controller.abort();
    }
    setStatus((current) => (current === "ready" ? "loading" : "waiting"));
    setMessage("Preparing a validated PDF preview…");

    const timeoutId = window.setTimeout(async () => {
      setStatus("loading");
      try {
        const response = await fetchWithTimeout(
          `${apiBaseUrl}/resume-templates/preview`,
          {
            method: "POST",
            cache: "no-store",
            headers: { "Content-Type": "application/json" },
            body: previewKey,
            signal: controller.signal,
          },
          PREVIEW_TIMEOUT_MS,
        );
        if (!response.ok) {
          throw new Error(await readPreviewError(response));
        }
        const pdf = await response.blob();
        if (controller.signal.aborted) return;
        const nextUrl = URL.createObjectURL(pdf);
        if (objectUrlRef.current) {
          URL.revokeObjectURL(objectUrlRef.current);
        }
        objectUrlRef.current = nextUrl;
        setPreviewUrl(nextUrl);
        setStatus("ready");
        setMessage("Preview updated");
      } catch (error) {
        if (controller.signal.aborted) return;
        setStatus("error");
        setMessage(
          apiUnavailableMessage(error, "Could not generate the preview."),
        );
      }
    }, debounceMs);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [
    apiBaseUrl,
    debounceMs,
    draft.designJson.accentColor,
    previewKey,
  ]);

  useEffect(
    () => () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
      }
    },
    [],
  );

  return (
    <div className="flex min-h-[560px] min-w-0 flex-col border-t border-border bg-[#090d12] lg:border-l lg:border-t-0">
      <div className="flex min-h-16 items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h3 className="text-sm font-bold text-white">Live preview</h3>
          <p
            className={`mt-0.5 text-xs ${
              status === "error" ? "text-red-300" : "text-muted"
            }`}
            role={status === "error" ? "alert" : undefined}
          >
            {message}
          </p>
        </div>
        {previewUrl ? (
          <a
            href={previewUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-white/[0.035] px-2.5 text-xs font-semibold text-muted transition hover:bg-white/[0.075] hover:text-white"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Open
          </a>
        ) : null}
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden p-3">
        {previewUrl ? (
          <iframe
            title="Resume template preview"
            src={previewUrl}
            className="h-full min-h-[510px] w-full rounded-md border border-white/10 bg-white"
          />
        ) : (
          <div className="flex max-w-xs flex-col items-center text-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-xl border border-border bg-white/[0.035]">
              {status === "loading" || status === "waiting" ? (
                <LoaderCircle className="h-6 w-6 animate-spin text-accent" />
              ) : (
                <FileText className="h-6 w-6 text-muted" />
              )}
            </span>
            <p className="mt-4 text-sm font-semibold text-white">
              {status === "error"
                ? "Preview unavailable"
                : "Generating your resume"}
            </p>
            <p className="mt-1.5 text-xs leading-5 text-muted">
              The validated PDF is returned directly to this tab and kept as a
              temporary browser Blob.
            </p>
          </div>
        )}

        {previewUrl && status === "loading" ? (
          <div className="absolute inset-3 flex items-center justify-center rounded-md bg-[#090d12]/65 backdrop-blur-[2px]">
            <span className="inline-flex items-center gap-2 rounded-md border border-border bg-[#111821] px-3 py-2 text-xs font-semibold text-white shadow-xl">
              <RefreshCw className="h-3.5 w-3.5 animate-spin text-accent" />
              Updating preview
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

async function readPreviewError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // The preview endpoint normally returns JSON errors, but keep a safe
    // fallback for proxies that replace the response body.
  }
  if (response.status === 429) {
    return "Preview limit reached. Wait a moment, then try again.";
  }
  return `Could not generate the preview (${response.status}).`;
}
