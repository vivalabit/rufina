import type {
  DirectCompanyDirection,
  ParserSearchForm,
} from "@/features/job-search/model/types";

export const directCompanyDirections: ReadonlyArray<{
  id: DirectCompanyDirection;
  label: string;
  targetRole: string;
}> = [
  { id: "information_technology", label: "Information Technology (IT)", targetRole: "Information Technology" },
  { id: "marketing", label: "Marketing", targetRole: "Marketing" },
  { id: "sales", label: "Sales", targetRole: "Sales" },
  { id: "finance_accounting", label: "Finance & Accounting", targetRole: "Finance and Accounting" },
  { id: "design", label: "Design", targetRole: "Design" },
  { id: "human_resources", label: "Human Resources", targetRole: "Human Resources and Recruiting" },
  { id: "operations", label: "Operations", targetRole: "Operations" },
  { id: "customer_support", label: "Customer Service & Support", targetRole: "Customer Service and Support" },
  { id: "engineering", label: "Engineering & Technical", targetRole: "Engineering and Technical" },
  { id: "healthcare", label: "Healthcare", targetRole: "Healthcare" },
  { id: "legal", label: "Legal", targetRole: "Legal" },
  { id: "all", label: "All directions", targetRole: "" },
];

export const defaultParserSearchForm: ParserSearchForm = {
  parsers: [],
  directCompaniesEnabled: false,
  directCompanyIds: [],
  directCompanyDirection: "information_technology",
  keywords: "",
  location: "",
  remote: "Any",
  experienceLevel: "Any",
  jobType: "Any",
  datePosted: "Any time",
  resultsLimit: "10",
  country: "Any",
  deduplicate: true,
  linkedinQueries: [],
  limitPerInput: "25",
  searchName: "",
  folder: "",
};

export const defaultLinkedInProfessionExperienceLevels = [
  "Entry level",
  "Internship",
];
