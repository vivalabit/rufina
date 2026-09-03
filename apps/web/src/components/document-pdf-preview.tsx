"use client";

import { useEffect, useRef, useState } from "react";
import {
  Download,
  Eye,
  FileText,
  LoaderCircle,
} from "lucide-react";

import {
  downloadGeneratedDocumentPdf,
  generatedDocumentDownloadUrl,
  generatedDocumentPdfUrl,
} from "@/features/applications/api/workspace-client";

type PreviewDocument = {
  id: string;
  title: string;
  currentVersion: number;
  versions: Array<{
    version: number;
    artifact?: {
      fileName?: string;
    } | null;
  }>;
};

function currentFileName(document: PreviewDocument) {
  return document.versions.find(
    (version) => version.version === document.currentVersion,
  )?.artifact?.fileName ?? "cover-letter.docx";
}

function pdfFileName(document: PreviewDocument) {
  const sourceFileName = currentFileName(document);
  return sourceFileName.toLowerCase().endsWith(".docx")
    ? `${sourceFileName.slice(0, -5)}.pdf`
    : `${sourceFileName}.pdf`;
}

export function DocumentPdfPreview({
  document,
  label,
}: {
  document: PreviewDocument;
  label: string;
}) {
  const [previewUrl, setPreviewUrl] = useState("");
  const previewUrlRef = useRef("");
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError("");

    async function loadPreview() {
      const blob = await downloadGeneratedDocumentPdf(
        document.id,
        document.currentVersion,
        controller.signal,
      );
      const nextUrl = typeof URL.createObjectURL === "function"
        ? URL.createObjectURL(blob)
        : "";
      if (previewUrlRef.current && typeof URL.revokeObjectURL === "function") {
        URL.revokeObjectURL(previewUrlRef.current);
      }
      previewUrlRef.current = nextUrl;
      setPreviewUrl(nextUrl);
      setStatus("ready");
    }

    void loadPreview().catch((caught) => {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "The PDF preview could not be loaded.");
    });

    return () => {
      controller.abort();
      if (previewUrlRef.current && typeof URL.revokeObjectURL === "function") {
        URL.revokeObjectURL(previewUrlRef.current);
      }
      previewUrlRef.current = "";
    };
  }, [document.currentVersion, document.id]);

  return (
    <section
      aria-label={`${label} PDF preview panel`}
      className="overflow-hidden rounded-2xl border border-border bg-black/15"
    >
      <div className="flex flex-col gap-3 border-b border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-[9px] font-black uppercase tracking-[0.12em] text-accent">
            PDF review
          </p>
          <h3 className="mt-1 text-sm font-bold text-foreground">
            Preview the exact {label.toLowerCase()}
          </h3>
          <p className="mt-1 text-[10px] leading-4 text-muted">
            {document.title} · v{document.currentVersion}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href={generatedDocumentPdfUrl(document.id)}
            download={pdfFileName(document)}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-[10px] font-bold text-foreground transition hover:bg-[#fff3e8]"
          >
            <Download className="h-3.5 w-3.5" />
            Download PDF
          </a>
          <a
            href={generatedDocumentDownloadUrl(document.id)}
            download={currentFileName(document)}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-[10px] font-bold text-foreground transition hover:bg-[#fff3e8]"
          >
            <FileText className="h-3.5 w-3.5" />
            Download DOCX
          </a>
        </div>
      </div>
      <div className="min-h-[520px] bg-[#ffffff] p-3">
        {status === "loading" ? (
          <div className="grid h-[496px] place-items-center text-center">
            <div>
              <LoaderCircle className="mx-auto h-6 w-6 animate-spin text-accent" />
              <p className="mt-2 text-[10px] font-bold text-muted">
                Preparing PDF preview…
              </p>
            </div>
          </div>
        ) : status === "ready" && previewUrl ? (
          <iframe
            title={`${label} PDF preview`}
            src={previewUrl}
            className="h-[496px] w-full rounded-lg border border-border bg-white"
          />
        ) : (
          <div
            role="alert"
            className="grid h-[496px] place-items-center rounded-lg border border-dashed border-accent/25 text-center"
          >
            <div className="max-w-sm px-4">
              <Eye className="mx-auto h-6 w-6 text-accent" />
              <p className="mt-2 text-[10px] font-bold leading-5 text-accent">
                {error || "The PDF preview could not be loaded."}
              </p>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
