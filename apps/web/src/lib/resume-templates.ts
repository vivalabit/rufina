export type ResumeTemplateId = string;

export type ResumeTemplateDensity =
  | "compact"
  | "standard"
  | "comfortable";

export type ResumeTemplatePageMargins = {
  top: number;
  right: number;
  bottom: number;
  left: number;
};

export type ResumeTemplateDesignTokens = {
  accentColor: string;
  fontFamily: string;
  fontScale: number;
  density: ResumeTemplateDensity;
  pageMargins: ResumeTemplatePageMargins;
  headingStyle: string;
  skillsStyle: string;
  sidebarWidth: number;
  sidebarSections: string[];
};

export type ResumeTemplateKind = "bundled" | "custom";

export type ResumeTemplate = {
  id: ResumeTemplateId;
  kind: ResumeTemplateKind;
  name: string;
  description: string;
  layout: "single_column" | "two_column";
  columns: 1 | 2;
  baseTemplateId: string;
  designJson: ResumeTemplateDesignTokens;
  version?: number | null;
  contentSha256?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type ResumeTemplateDraft = {
  name: string;
  baseTemplateId: string;
  designJson: ResumeTemplateDesignTokens;
};
