import type { JobFilters, JobSortBy, ManualJobDraft } from "@/features/jobs/model/types";

export const recentJobWindowMs = 24 * 60 * 60 * 1000;

export const defaultManualJobDraft: ManualJobDraft = {
  title: "",
  company: "",
  location: "",
  applyUrl: "",
  overview: "",
};

export const defaultJobFilters: JobFilters = {
  location: "Any",
  remote: "Any",
  salary: "Any",
  experience: "Any",
  type: "Any",
  match: "Any",
};

export const remoteFilterOptions = [
  { value: "remote", label: "Remote only" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
];

export const salaryFilterOptions = [
  { value: "listed", label: "Salary listed" },
  { value: "100000", label: "$100k+" },
  { value: "120000", label: "$120k+" },
  { value: "140000", label: "$140k+" },
];

export const experienceFilterOptions = [
  { value: "entry", label: "Entry / Junior" },
  { value: "mid", label: "Mid-level" },
  { value: "senior", label: "Senior+" },
];

export const matchFilterOptions = [
  { value: "70", label: "70%+" },
  { value: "80", label: "80%+" },
  { value: "90", label: "90%+" },
];

export const jobSortOptions: JobSortBy[] = ["AI Match", "Time", "Salary"];
