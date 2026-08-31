export type ParserId = "linkedin" | "indeed" | "jobs_ch";

export type ActiveSearchSource = ParserId | "direct_companies";

export type DirectCompanyDirection =
  | "information_technology"
  | "marketing"
  | "sales"
  | "finance_accounting"
  | "design"
  | "human_resources"
  | "operations"
  | "customer_support"
  | "engineering"
  | "healthcare"
  | "legal"
  | "all";

export type LinkedInDiscoveryQueryDraft = {
  keyword: string;
  experienceLevels: string[];
  jobType?: string | null;
  selectiveSearch: boolean;
};

export type ParserSearchForm = {
  parsers: ParserId[];
  directCompaniesEnabled: boolean;
  directCompanyIds: string[];
  directCompanyDirection: DirectCompanyDirection;
  keywords: string;
  location: string;
  remote: string;
  experienceLevel: string;
  jobType: string;
  datePosted: string;
  resultsLimit: string;
  country: string;
  deduplicate: boolean;
  linkedinQueries: LinkedInDiscoveryQueryDraft[];
  limitPerInput: string;
  searchName: string;
  folder: string;
};

export type SourceSearchDraft = Pick<
  ParserSearchForm,
  | "keywords"
  | "location"
  | "remote"
  | "experienceLevel"
  | "jobType"
  | "datePosted"
  | "resultsLimit"
  | "country"
  | "deduplicate"
  | "linkedinQueries"
  | "limitPerInput"
>;

export type ParserSearchConfig = {
  id: string;
  name: string;
  form: ParserSearchForm;
  filters: Record<string, unknown>;
  updatedAt: string;
};

export type ParserSearchStatus = "idle" | "loading" | "ready" | "error";
