import type { ManualJobDraft } from "@/features/jobs/model/types";
import { normalizeExternalUrl } from "@/shared/formatting/urls";
import type { Job } from "@/shared/types/job";

const manualJobSkillPatterns: Array<{ label: string; pattern: RegExp }> = [
  { label: "IPX", pattern: /\bipx\b/i },
  { label: "HVAC", pattern: /\bhvac\b/i },
  { label: "IoT", pattern: /\biot\b/i },
  { label: "Embedded systems", pattern: /\bembedded\b/i },
  { label: "Firmware", pattern: /\bfirmware\b/i },
  {
    label: "IP networking",
    pattern: /\bip\s+(network|networking|protocol)|\bnetworking\b/i,
  },
  { label: "Cybersecurity", pattern: /\bcyber\s?security|security\b/i },
  { label: "Cloud", pattern: /\bcloud\b/i },
  { label: "AWS", pattern: /\baws\b/i },
  { label: "Azure", pattern: /\bazure\b/i },
  { label: "GCP", pattern: /\bgcp|google cloud\b/i },
  { label: "Python", pattern: /\bpython\b/i },
  { label: "JavaScript", pattern: /\bjavascript|js\b/i },
  { label: "TypeScript", pattern: /\btypescript|ts\b/i },
  { label: "React", pattern: /\breact\b/i },
  { label: "Node.js", pattern: /\bnode(?:\.js)?\b/i },
  { label: "Java", pattern: /\bjava\b/i },
  { label: "C++", pattern: /\bc\+\+\b/i },
  { label: "C#", pattern: /\bc#\b/i },
  { label: "SQL", pattern: /\bsql\b/i },
  {
    label: "Data analysis",
    pattern: /\bdata analysis|analytics|analyse|analysis\b/i,
  },
  { label: "Machine learning", pattern: /\bmachine learning|ml\b/i },
  { label: "AI", pattern: /\bartificial intelligence|\bai\b/i },
  { label: "Figma", pattern: /\bfigma\b/i },
  { label: "UX", pattern: /\bux|user experience\b/i },
  { label: "UI", pattern: /\bui|user interface\b/i },
  {
    label: "Product management",
    pattern: /\bproduct management|product owner\b/i,
  },
  {
    label: "Project management",
    pattern: /\bproject management|coordination|coordinate\b/i,
  },
  { label: "Agile", pattern: /\bagile|scrum|kanban\b/i },
  { label: "SAP", pattern: /\bsap\b/i },
  { label: "Excel", pattern: /\bexcel\b/i },
  { label: "Power BI", pattern: /\bpower\s?bi\b/i },
  {
    label: "Communication",
    pattern: /\bcommunication|stakeholder|presentation\b/i,
  },
  { label: "English", pattern: /\benglish\b/i },
  { label: "German", pattern: /\bgerman|deutsch\b/i },
  { label: "French", pattern: /\bfrench|franzosisch|francais\b/i },
];

function splitJobDescriptionItems(value: string) {
  return value
    .replace(/\r/g, "")
    .split(/\n+|[.;]\s+/)
    .map((item) => item.replace(/^[-*•\d.)\s]+/, "").trim())
    .filter((item) => item.length >= 8);
}

function truncateJobText(value: string, maxLength = 180) {
  const normalizedValue = value.replace(/\s+/g, " ").trim();
  if (normalizedValue.length <= maxLength) return normalizedValue;
  return `${normalizedValue.slice(0, maxLength - 1).trim()}...`;
}

function uniqueJobItems(items: string[], limit: number) {
  return Array.from(
    new Map(
      items
        .map((item) => truncateJobText(item))
        .filter(Boolean)
        .map((item) => [item.toLowerCase(), item]),
    ).values(),
  ).slice(0, limit);
}

function inferManualJobType(text: string) {
  if (/\bworking student\b/i.test(text)) return "Working student";
  if (/\bintern(ship)?|trainee\b/i.test(text)) return "Internship";
  if (/\bfreelance|self-employed\b/i.test(text)) return "Freelance";
  if (/\bcontract|temporary|befristet\b/i.test(text)) return "Contract";
  if (/\bpart[-\s]?time|\b[2-8]0\s?%/i.test(text)) return "Part-time";
  if (/\bfull[-\s]?time|100\s?%/i.test(text)) return "Full-time";
  return "Not specified";
}

function inferManualJobExperience(text: string) {
  if (
    /\bworking student\b|\bintern(ship)?|trainee|student|entry[-\s]?level|junior|graduate\b/i.test(
      text,
    )
  ) {
    return "Entry level";
  }
  if (/\bassociate\b/i.test(text)) return "Associate";
  if (/\bsenior|sr\.?|lead|principal|staff|head of|director\b/i.test(text)) {
    return "Senior";
  }
  if (/\bmid[-\s]?level|professional|experienced\b/i.test(text)) {
    return "Mid-level";
  }

  const years = text.match(/\b(\d+)\+?\s*(?:years?|yrs?)\b/i)?.[1];
  if (!years) return "Not specified";

  const yearCount = Number.parseInt(years, 10);
  if (yearCount >= 5) return `${yearCount}+ years`;
  if (yearCount >= 2) return `${yearCount}+ years`;
  return "Entry level";
}

function inferManualJobSalary(text: string) {
  const salaryMatch = text.match(
    /(?:CHF|EUR|USD|GBP|[$€£])\s?[\d'.,]+(?:\s?[kK])?(?:\s?[-–]\s?(?:CHF|EUR|USD|GBP|[$€£])?\s?[\d'.,]+(?:\s?[kK])?)?/,
  );
  return salaryMatch?.[0].replace(/\s+/g, " ").trim() || "Not specified";
}

function inferManualJobDepartment(text: string) {
  const departmentPatterns: Array<{ label: string; pattern: RegExp }> = [
    { label: "Product", pattern: /\bproduct\b/i },
    { label: "Design", pattern: /\bdesign|ux|ui\b/i },
    {
      label: "Engineering",
      pattern: /\bengineering|software|developer|embedded|firmware\b/i,
    },
    { label: "IT", pattern: /\bit\b|information technology|network|cyber/i },
    { label: "Data", pattern: /\bdata|analytics|machine learning|ai\b/i },
    { label: "Marketing", pattern: /\bmarketing|brand|campaign\b/i },
    { label: "Sales", pattern: /\bsales|business development|account\b/i },
    { label: "Operations", pattern: /\boperations|supply chain|logistics\b/i },
    { label: "Finance", pattern: /\bfinance|accounting|controlling\b/i },
    { label: "People", pattern: /\bhr|people|talent|recruiting\b/i },
    {
      label: "Manufacturing",
      pattern: /\bmanufacturing|production|quality\b/i,
    },
  ];
  const departments = departmentPatterns
    .filter((item) => item.pattern.test(text))
    .map((item) => item.label);

  return departments.length > 0
    ? departments.slice(0, 2).join(" / ")
    : "Manual entry";
}

function extractManualJobSkills(text: string) {
  const matchedSkills = manualJobSkillPatterns
    .filter((item) => item.pattern.test(text))
    .map((item) => item.label);

  return uniqueJobItems(matchedSkills, 14);
}

function extractManualJobRequirements(description: string, title: string) {
  const items = splitJobDescriptionItems(description);
  const requirementItems = items.filter((item) =>
    /\brequire|qualification|profile|experience|knowledge|skill|degree|student|fluent|english|german|must|you have|you bring|familiar|proficient|able to\b/i.test(
      item,
    ),
  );
  const uniqueRequirements = uniqueJobItems(requirementItems, 6);

  return uniqueRequirements.length > 0
    ? uniqueRequirements
    : uniqueJobItems(
        [
          `Relevant background for ${title}`,
          "Review the vacancy description before applying",
        ],
        2,
      );
}

function extractManualJobResponsibilities(description: string) {
  const items = splitJobDescriptionItems(description);
  const responsibilityItems = items.filter((item) =>
    /\bresponsib|support|develop|create|design|analy[sz]e|manage|maintain|coordinate|collaborate|contribute|work with|implement|build|prepare\b/i.test(
      item,
    ),
  );
  const uniqueResponsibilities = uniqueJobItems(responsibilityItems, 6);

  return uniqueResponsibilities.length > 0
    ? uniqueResponsibilities
    : ["Track application progress", "Keep next steps and events up to date"];
}

export function analyzeManualJobDescription(draft: ManualJobDraft) {
  const title = draft.title.trim();
  const description = draft.overview.trim();
  const analysisText = [title, draft.company, draft.location, description]
    .filter(Boolean)
    .join("\n");
  const skills = extractManualJobSkills(analysisText);

  return {
    type: inferManualJobType(analysisText),
    salary: inferManualJobSalary(analysisText),
    experience: inferManualJobExperience(analysisText),
    department: inferManualJobDepartment(analysisText),
    responsibilities: extractManualJobResponsibilities(description),
    requirements: extractManualJobRequirements(description, title),
    skills: skills.length > 0 ? skills : ["Manual entry"],
  };
}

type ManualJobFactoryDependencies = {
  createId: (prefix: string) => string;
  now: () => string;
};

export function createManualJobFromDraft(
  draft: ManualJobDraft,
  dependencies: ManualJobFactoryDependencies,
): Job {
  const title = draft.title.trim();
  const company = draft.company.trim();
  const location = draft.location.trim() || "Not specified";
  const applyUrl = normalizeExternalUrl(draft.applyUrl);
  const analysis = analyzeManualJobDescription(draft);

  return {
    id: dependencies.createId("manual-job"),
    company,
    title,
    location,
    type: analysis.type,
    salary: analysis.salary,
    posted: "Manual entry",
    experience: analysis.experience,
    department: analysis.department,
    match: 50,
    logo: "manual",
    overview:
      draft.overview.trim() ||
      "Manually added vacancy. Add notes, events, and next steps from the application tracker.",
    responsibilities: analysis.responsibilities,
    requirements: analysis.requirements,
    skills: analysis.skills,
    salaryAverage: "N/A",
    salaryMin: "N/A",
    salaryMax: "N/A",
    recommendations: [],
    companyInfo: `${company} vacancy added manually${applyUrl ? `: ${applyUrl}` : "."}`,
    reviews: ["This vacancy was added manually and has not been scored yet."],
    similarJobs: [],
    applyUrl: applyUrl || undefined,
    sourceUrl: applyUrl || undefined,
    addedAt: dependencies.now(),
  };
}
