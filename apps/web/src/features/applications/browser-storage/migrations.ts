import { decodeDataUrl, isInlineDataUrl } from "@/shared/browser-storage/data-url";
import type { ApplicationDocument } from "@/shared/types/application";

import {
  legacyDemoApplicationIds,
  normalizeApplicationDocuments,
} from "./normalizers";

export type LegacyApplicationAttachmentMetadata = {
  fileName: string;
  title: string;
  legacyDocumentId?: string;
};

export type LegacyApplicationDocumentMigrationDependencies = {
  uploadAttachment: (
    applicationId: string,
    file: Blob,
    metadata: LegacyApplicationAttachmentMetadata,
  ) => Promise<ApplicationDocument>;
  isPermanentUploadError: (error: unknown) => boolean;
};

export function extractLegacyApplicationDocuments(value: unknown) {
  const documentsByApplication = new Map<string, ApplicationDocument[]>();
  if (!Array.isArray(value)) return documentsByApplication;

  for (const candidate of value) {
    if (!candidate || typeof candidate !== "object") continue;
    const application = candidate as Record<string, unknown>;
    if (typeof application.id !== "string" || !application.id.trim()) continue;
    if (legacyDemoApplicationIds.has(application.id)) continue;

    const documents = normalizeApplicationDocuments(application.documents)
      .filter((document) => Boolean(document.legacyDataUrl));
    if (documents.length > 0) {
      documentsByApplication.set(application.id, documents);
    }
  }

  return documentsByApplication;
}

export async function migrateLegacyApplicationDocuments(
  legacyDocuments: Map<string, ApplicationDocument[]>,
  dependencies: LegacyApplicationDocumentMigrationDependencies,
): Promise<{
  documents: Map<string, ApplicationDocument[]>;
  warnings: string[];
}> {
  const migrated = new Map<string, ApplicationDocument[]>();
  const warnings: string[] = [];

  for (const [applicationId, documents] of legacyDocuments) {
    const uploaded: ApplicationDocument[] = [];
    for (const document of documents) {
      if (!isInlineDataUrl(document.legacyDataUrl)) continue;

      let blob: Blob | null = null;
      try {
        blob = decodeDataUrl(document.legacyDataUrl as string);
      } catch {
        warnings.push(
          `Malformed legacy application document ${document.fileName} was removed.`,
        );
      }
      if (!blob) continue;

      try {
        uploaded.push(
          await dependencies.uploadAttachment(applicationId, blob, {
            fileName: document.fileName,
            title: document.title,
            legacyDocumentId: document.id,
          }),
        );
      } catch (error) {
        if (dependencies.isPermanentUploadError(error)) {
          warnings.push(
            `Legacy application document ${document.fileName} was removed because it is not a safe supported file.`,
          );
          continue;
        }
        throw error;
      }
    }
    migrated.set(applicationId, uploaded);
  }

  return { documents: migrated, warnings };
}
