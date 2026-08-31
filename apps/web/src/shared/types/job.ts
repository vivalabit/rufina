import type { AiSource } from "@/lib/ai-source";

export type AiMatchMetadata = {
  version: string;
  revision?: string;
  fingerprint?: string;
  cacheKey: string;
  source: AiSource;
  backend?: AiSource;
  score: number;
  confidence: "low" | "medium" | "high";
  breakdown: Record<string, number>;
  reasons: string[];
  gaps: string[];
  applicationGuide?: {
    language: "English" | "German";
    positioning: string;
    readiness?: "ready" | "needs_confirmation" | "weak_fit";
    roleMission?: string;
    hiringPriorities?: string[];
    mustHave?: string[];
    niceToHave?: string[];
    hardConstraints?: string[];
    evidenceMatrix?: Array<{
      requirement: string;
      importance: "required" | "preferred";
      status: "verified" | "transferable" | "needs_confirmation" | "missing";
      evidence: string;
      action: string;
      sourceIds?: string[];
      sources?: Array<{ id: string; label: string; excerpt: string }>;
    }>;
    clarificationQuestions?: Array<{
      id: string;
      requirement: string;
      question: string;
      why: string;
      claimIfConfirmed: string;
      blocking: boolean;
    }>;
    resumePlan?: {
      targetHeadline: string;
      summaryFocus: string;
      evidenceToLead: string[];
      bulletStrategy: string[];
    };
    coverLetterPlan?: {
      openingAngle: string;
      proofPoints: string[];
      motivationAngle: string;
    };
    cvImprovements: string[];
    coverLetterStrategy: string[];
    risks: string[];
    keywords: string[];
    applicationQuestions: string[];
    finalChecklist: string[];
  };
  explanation?: string;
  rawExplanation?: string;
  heuristicScore?: number;
  updatedAt?: string;
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
