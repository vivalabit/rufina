import type { ApplicationEvent } from "@/shared/types/application";

export type StoredApplicationPayload = {
  id: string;
  data: unknown;
  created_at?: string;
  updated_at?: string;
  revision?: number;
};

export type WorkspaceSourceFilePayload = {
  id: string;
  applicationId: string;
  category: string;
  title: string;
  language: string;
  fileName: string;
  fileSize: string;
  sizeBytes?: number;
  fileType: string;
  uploadedAt: string;
  downloadUrl: string;
};

export type GeneratedApplicationDocumentPayload = {
  id: string;
  title: string;
  type: "cover_letter" | "tailored_resume";
  currentVersion: number;
  updatedAt: string;
  versions: Array<{
    version: number;
    artifact?: {
      fileName?: string;
      contentType?: string;
    } | null;
  }>;
};

export type ApplicationEventApiPayload = {
  id: string;
  application_id: string;
  data: ApplicationEvent;
};

export type StoredApplicationEventPayload = ApplicationEventApiPayload & {
  created_at?: string;
  updated_at?: string;
  revision?: number;
};
