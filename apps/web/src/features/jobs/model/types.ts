export type BulkAnalysisScope = "recent" | "missing";

export type ManualJobDraft = {
  title: string;
  company: string;
  location: string;
  applyUrl: string;
  overview: string;
};

export type JobFilterKey =
  | "location"
  | "remote"
  | "salary"
  | "experience"
  | "type"
  | "match";

export type JobFilters = Record<JobFilterKey, string>;

export type JobSortBy = "AI Match" | "Time" | "Salary";
