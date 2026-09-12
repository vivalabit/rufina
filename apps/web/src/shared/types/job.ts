import type { AiSource } from "@/lib/ai-source";

export type AiMatchMetadata = {
  version: string;
  revision?: string;
  fingerprint?: string;
  cacheKey: string;
  source: AiSource;
  backend: AiSource;
  score: number;
  profileHash: string;
  vacancyHash: string;
  model: string;
  promptVersion: string;
  updatedAt: string;
  providerError?: string;
};

export type JobRecommendation = {
  text: string;
  gain: string;
  why?: string;
  impact?: string;
  action?: string;
};

export type Job = {
  id: string;
  company: string;
  title: string;
  location: string;
  type: string;
  salary: string;
  posted: string;
  experience: string;
  department: string;
  match: number;
  logo: "stripe" | "figma" | "linkedin" | "indeed" | "jobs_ch" | "company" | "manual";
  overview: string;
  responsibilities: string[];
  requirements: string[];
  skills: string[];
  salaryAverage: string;
  salaryMin: string;
  salaryMax: string;
  recommendations: JobRecommendation[];
  companyInfo: string;
  reviews: string[];
  similarJobs: string[];
  applyUrl?: string;
  sourceUrl?: string;
  addedAt?: string;
  archived?: boolean;
  archivedAt?: string;
  aiMatch?: AiMatchMetadata;
};
