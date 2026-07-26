"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Download,
  ExternalLink,
  FileText,
  LoaderCircle,
  Minus,
  Plus,
  Redo2,
  RefreshCw,
  Undo2,
} from "lucide-react";

import { apiUnavailableMessage, fetchWithTimeout } from "@/lib/api-client";
import type { ResumeTemplateDraft } from "@/lib/resume-templates";

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
  const [zoom, setZoom] = useState(70);
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
  const previewSrc = previewUrl ? `${previewUrl}#page=1&zoom=${zoom}` : null;

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
  }, [apiBaseUrl, debounceMs, draft.designJson.accentColor, previewKey]);

  useEffect(
    () => () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
      }
    },
    [],
  );

  return (
    <div className="flex min-h-[780px] min-w-0 flex-col border-t border-white/[0.12] bg-[#080c10] xl:min-h-[936px] xl:border-l xl:border-t-0">
      <div className="flex min-h-[84px] items-center justify-between gap-3 border-b border-white/[0.12] px-5 py-3">
        <div>
          <h3 className="text-[13px] font-bold uppercase tracking-[0.04em] text-white">
            Live preview
          </h3>
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
            className="inline-flex h-10 items-center gap-2 rounded-md border border-white/[0.14] bg-white/[0.02] px-4 text-xs font-bold text-[#e4e8ed] transition hover:bg-white/[0.07] hover:text-white"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Open
          </a>
        ) : null}
      </div>

      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden p-5 pt-4">
        {previewUrl ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-white/[0.12] bg-[#11161b]">
            <div className="flex h-[66px] shrink-0 items-center justify-between border-b border-white/[0.1] bg-[#0c1116] px-5">
              <div className="flex items-center gap-3 text-sm font-semibold text-white">
                <span>1</span>
                <span className="text-[#8d949d]">/</span>
                <span>1</span>
                <span className="mx-1 h-7 w-px bg-white/[0.12]" />
                <PreviewToolButton
                  label="Zoom out"
                  onClick={() => setZoom((value) => Math.max(40, value - 10))}
                >
                  <Minus className="h-4 w-4" />
                </PreviewToolButton>
                <PreviewToolButton
                  label="Zoom in"
                  onClick={() => setZoom((value) => Math.min(140, value + 10))}
                >
                  <Plus className="h-4 w-4" />
                </PreviewToolButton>
                <select
                  aria-label="Preview zoom"
                  value={zoom}
                  onChange={(event) => setZoom(Number(event.target.value))}
                  className="h-10 rounded-md border border-white/[0.14] bg-[#0c1116] px-3 text-sm font-bold text-white outline-none hover:bg-white/[0.04]"
                >
                  {[50, 60, 70, 80, 90, 100, 120].map((value) => (
                    <option key={value} value={value}>
                      {value}%
                    </option>
                  ))}
                </select>
                <span className="mx-1 h-7 w-px bg-white/[0.12]" />
                <PreviewToolButton label="Undo" disabled>
                  <Undo2 className="h-4 w-4" />
                </PreviewToolButton>
                <PreviewToolButton label="Redo" disabled>
                  <Redo2 className="h-4 w-4" />
                </PreviewToolButton>
              </div>
              <a
                href={previewUrl}
                download={`${draft.name || "resume-template"}.pdf`}
                aria-label="Download preview"
                className="flex h-9 w-9 items-center justify-center rounded-md text-white transition hover:bg-white/[0.07]"
              >
                <Download className="h-5 w-5" />
              </a>
            </div>
            <div className="relative min-h-0 flex-1 overflow-hidden bg-[#171b1f]">
              <iframe
                title="Resume template preview"
                src={previewSrc ?? previewUrl}
                className="absolute -top-14 left-0 h-[calc(100%+3.5rem)] w-full border-0 bg-[#171b1f]"
              />
            </div>
          </div>
        ) : (
          <div className="flex flex-1 items-center justify-center">
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
          </div>
        )}

        {previewUrl && status === "loading" ? (
          <div className="absolute inset-5 top-4 flex items-center justify-center rounded-lg bg-[#090d12]/65 backdrop-blur-[2px]">
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

function PreviewToolButton({
  label,
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="flex h-9 w-9 items-center justify-center rounded-md text-[#e8ebef] transition hover:bg-white/[0.07] disabled:cursor-not-allowed disabled:text-[#737a83]"
    >
      {children}
    </button>
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
