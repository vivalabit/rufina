export type CandidateProfile = {
  avatar_url: string;
  name: string;
  current_role: string;
  desired_role: string;
  location: string;
  work_format: string;
  headline: string;
  linkedin: string;
  github: string;
  portfolio: string;
  personal_site: string;
  experience: string;
  skills: string;
  education: string;
  job_preferences: string;
  dealbreakers: string;
  additional_notes: string;
  documents: string;
  avatar_file_id: string;
  resume_file_id: string;
  resume_file_name: string;
  resume_file_size: string;
  resume_updated_at: string;
  resume_download_url: string;
};

export type ExperienceEntry = {
  id: string;
  title: string;
  company: string;
  employment_type: string;
  location: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  description: string;
};

export type EducationEntry = {
  id: string;
  institution: string;
  credential: string;
  field_of_study: string;
  location: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  description: string;
};

export type DocumentEntry = {
  id: string;
  title: string;
  category: string;
  language: string;
  issuer: string;
  notes: string;
  file_name: string;
  file_size: string;
  file_type: string;
  uploaded_at: string;
  download_url: string;
  pending_file?: File;
};

export type PreferenceListField = "desired_roles" | "locations" | "industries" | "languages";
export type PreferenceToggleField = "seniority" | "work_formats" | "employment_types" | "company_sizes" | "priorities";
export type PreferenceAnyField =
  | PreferenceListField
  | PreferenceToggleField
  | "salary"
  | "work_authorization";
export type PreferenceInputs = Record<PreferenceListField, string>;

export type JobPreferences = {
  desired_roles: string[];
  seniority: string[];
  locations: string[];
  work_formats: string[];
  employment_types: string[];
  industries: string[];
  salary_min: string;
  salary_currency: string;
  work_authorization: string;
  swiss_permit_status: string;
  languages: string[];
  company_sizes: string[];
  priorities: string[];
  notes: string;
  no_preference: PreferenceAnyField[];
};
