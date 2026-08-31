import type {
  CandidateProfile,
  DocumentEntry,
  EducationEntry,
  ExperienceEntry,
  JobPreferences,
  PreferenceAnyField,
  PreferenceInputs,
  PreferenceListField,
} from "@/shared/types/profile";

export const defaultCandidateProfile: CandidateProfile = {
  avatar_url: "/avatars/default-pug.png",
  name: "",
  current_role: "",
  desired_role: "",
  location: "",
  work_format: "",
  headline: "",
  linkedin: "",
  github: "",
  portfolio: "",
  personal_site: "",
  experience: "",
  skills: "",
  education: "",
  job_preferences: "",
  dealbreakers: "",
  additional_notes: "",
  documents: "",
  avatar_file_id: "",
  resume_file_id: "",
  resume_file_name: "",
  resume_file_size: "",
  resume_updated_at: "",
  resume_download_url: "",
};

export const candidateProfileDataFields: Array<keyof CandidateProfile> = [
  "name", "current_role", "desired_role", "location", "work_format", "headline",
  "linkedin", "github", "portfolio", "personal_site", "experience", "skills",
  "education", "job_preferences", "dealbreakers", "additional_notes",
];

export const defaultExperienceDraft: ExperienceEntry = {
  id: "", title: "", company: "", employment_type: "Full-time", location: "",
  start_date: "", end_date: "", is_current: false, description: "",
};

export const defaultEducationDraft: EducationEntry = {
  id: "", institution: "", credential: "", field_of_study: "", location: "",
  start_date: "", end_date: "", is_current: false, description: "",
};

export const defaultDocumentDraft: DocumentEntry = {
  id: "", title: "", category: "Other", language: "", issuer: "", notes: "",
  file_name: "", file_size: "", file_type: "", uploaded_at: "", download_url: "",
};

export const documentCategories = [
  "CV / Resume", "Diploma", "Certificate", "Recommendation", "Work permit",
  "Portfolio", "Transcript", "Other",
];

export const defaultJobPreferences: JobPreferences = {
  desired_roles: [], seniority: [], locations: [], work_formats: [], employment_types: [],
  industries: [], salary_min: "", salary_currency: "CHF", work_authorization: "",
  swiss_permit_status: "", languages: [], company_sizes: [], priorities: [], notes: "",
  no_preference: [],
};

export const defaultPreferenceInputs: PreferenceInputs = {
  desired_roles: "", locations: "", industries: "", languages: "",
};

export const preferenceOptions = {
  seniority: ["Intern", "Entry-level", "Junior", "Mid-level", "Senior"],
  work_formats: ["Remote", "Hybrid", "On-site", "Relocation"],
  employment_types: ["Full-time", "Part-time", "Internship", "Contract", "Freelance"],
  company_sizes: ["Startup", "Scale-up", "Mid-size", "Enterprise"],
  priorities: ["Salary", "Learning", "Remote", "Relocation", "Tech stack", "Stability", "Fast hiring"],
  work_authorization: ["Authorized to work", "Needs sponsorship", "EU/EFTA eligible", "Swiss permit", "Student permit", "Not sure"],
  swiss_permit_status: ["B permit", "C permit", "L permit", "G permit", "Ci permit", "S permit", "Other / in progress"],
};

export const preferenceSuggestions: Record<PreferenceListField, string[]> = {
  desired_roles: ["Python Developer", "Backend Developer", "AI Engineer", "Full-stack Developer", "Data Engineer", "Machine Learning Engineer"],
  locations: ["Switzerland", "Zurich", "Remote Europe", "Germany", "Austria", "Netherlands", "Remote worldwide"],
  industries: ["AI", "SaaS", "FinTech", "HealthTech", "Developer tools", "EdTech", "E-commerce", "Cybersecurity"],
  languages: ["English C1", "English B2", "German A2", "German B1", "French B1", "Russian native"],
};

export const suggestedDealbreakers = [
  "No onsite-only roles", "Remote or hybrid only", "Minimum salary CHF 100,000",
  "No contract roles", "Full-time only", "No relocation outside Switzerland",
  "No unpaid internships", "No roles requiring fluent German", "No crypto or gambling industry",
  "Must support Swiss permit",
];

export const preferenceListLabels: Record<PreferenceListField, { label: string; placeholder: string }> = {
  desired_roles: { label: "Desired roles", placeholder: "Python Developer, AI Engineer..." },
  locations: { label: "Locations", placeholder: "Zurich, Switzerland, Remote Europe..." },
  industries: { label: "Industries", placeholder: "AI, SaaS, FinTech..." },
  languages: { label: "Languages", placeholder: "English C1, German A2..." },
};

export const preferenceSummaryLabels: Record<PreferenceAnyField, string> = {
  desired_roles: "Roles", seniority: "Seniority", locations: "Locations",
  work_formats: "Work format", employment_types: "Employment", industries: "Industries",
  salary: "Salary floor", work_authorization: "Authorization", languages: "Languages",
  company_sizes: "Company size", priorities: "Priorities",
};
