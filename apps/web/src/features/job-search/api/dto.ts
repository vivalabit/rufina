import type { ParserId } from "@/features/job-search/model/types";

export type JobSearchConfigPayload = {
  id: string;
  name: string;
  filters: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type JobSourceConfigPayload = {
  id: string;
  name: string;
  configId: string;
  source: ParserId;
  filters: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type JobSearchRunPayload = {
  id: string;
  runType: "manual" | "automatic";
  sources: string[];
  status: string;
  jobsFound: number;
  jobsAlreadyKnown: number;
  jobsDiscoveredNew: number;
  jobsDiscoveredUpdated: number;
  jobsAlreadyObserved: number;
  jobsScreened: number;
  jobsPassed: number;
  jobsRejected: number;
  jobsUncertain: number;
  jobsAdded: number;
  jobsAnalyzed: number;
  screeningErrors: number;
  jobsScreeningAiCalls: number;
  sourceErrors: Record<string, string>;
  startedAt: string;
  completedAt?: string | null;
  warning?: string | null;
};
