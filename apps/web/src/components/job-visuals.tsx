"use client";

import Image from "next/image";
import {
  BarChart3,
  BrainCircuit,
  BriefcaseBusiness,
  Cloud,
  Code2,
  Database,
  FlaskConical,
  Palette,
  Server,
  ShieldCheck,
  Smartphone,
  TimerReset,
} from "lucide-react";

import { getAiMatchPresentation } from "@/features/jobs/model/ai-match";
import { getDirectCompanyByJobId } from "@/lib/direct-company-catalog";
import { cn } from "@/lib/utils";
import type { Job } from "@/shared/types/job";

type JobRoleIconProps = {
  job: Job;
  large?: boolean;
  compact?: boolean;
};

const matchStateStyles = {
  calculating: "text-accent",
  current: "text-accent",
  outdated: "text-[#9a5b08]",
  failed: "text-red-700",
  missing: "text-muted",
} as const;

export function JobMatchIndicator({
  job,
  isCalculating = false,
  isError = false,
  className,
}: {
  job: Job;
  isCalculating?: boolean;
  isError?: boolean;
  className?: string;
}) {
  const presentation = getAiMatchPresentation(job, {
    isCalculating,
    isError,
  });
  const score = presentation.score === null ? "—" : `${presentation.score}%`;
  const accessibleLabel = `AI match: ${score} · ${presentation.label}`;
  const hasScore = presentation.score !== null;
  const normalizedMatch = Math.max(0, Math.min(100, presentation.score ?? 0));
  const radius = 18.5;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = presentation.state === "calculating"
    ? circumference * 0.75
    : circumference * (1 - normalizedMatch / 100);

  return (
    <div
      role="img"
      className={cn(
        "relative h-10 w-10 shrink-0 2xl:h-12 2xl:w-12",
        matchStateStyles[presentation.state],
        className,
      )}
      aria-label={accessibleLabel}
      title={accessibleLabel}
    >
      <svg className="block h-full w-full" viewBox="0 0 48 48" aria-hidden="true">
        <circle
          cx="24"
          cy="24"
          r={radius}
          fill="none"
          stroke="var(--color-parchment-shadow)"
          strokeWidth="3"
        />
        <g
          className={cn(
            "origin-center",
            presentation.state === "calculating" && "motion-safe:animate-spin",
          )}
        >
          <circle
            cx="24"
            cy="24"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            transform="rotate(-90 24 24)"
          />
        </g>
        <text
          x="24"
          y="24"
          fill={presentation.state === "failed" ? "currentColor" : "var(--color-ink-black)"}
          fontSize="13"
          fontWeight="700"
          textAnchor="middle"
          dominantBaseline="central"
          letterSpacing="0"
        >
          {hasScore ? (
            <>
              <tspan>{normalizedMatch}</tspan>
              <tspan fill="var(--color-warm-stone)" fontSize="8" fontWeight="700">%</tspan>
            </>
          ) : presentation.state === "calculating" ? (
            "…"
          ) : presentation.state === "failed" ? (
            "!"
          ) : (
            "AI"
          )}
        </text>
      </svg>
      {presentation.state === "outdated" ? (
        <TimerReset
          className="absolute -bottom-0.5 -right-0.5 h-3.5 w-3.5 rounded-full bg-[#fff8f1]"
          aria-hidden="true"
        />
      ) : null}
    </div>
  );
}

const jobRoleVisuals = {
  ai: { label: "AI / Machine Learning", icon: BrainCircuit, className: "border-accent/25 bg-accent/10 text-accent" },
  analytics: { label: "Analytics", icon: BarChart3, className: "border-accent/25 bg-accent/10 text-accent" },
  backend: { label: "Backend", icon: Server, className: "border-accent/25 bg-accent/10 text-accent" },
  data: { label: "Data Engineering", icon: Database, className: "border-accent/25 bg-accent/10 text-accent" },
  design: { label: "Product Design", icon: Palette, className: "border-accent/25 bg-accent/10 text-accent" },
  devops: { label: "DevOps / Cloud", icon: Cloud, className: "border-accent/25 bg-accent/10 text-accent" },
  frontend: { label: "Frontend", icon: Code2, className: "border-accent/25 bg-accent/10 text-accent" },
  mobile: { label: "Mobile", icon: Smartphone, className: "border-accent/25 bg-accent/10 text-accent" },
  qa: { label: "Quality Assurance", icon: FlaskConical, className: "border-accent/25 bg-accent/10 text-accent" },
  security: { label: "Security", icon: ShieldCheck, className: "border-accent/25 bg-accent/10 text-accent" },
  software: { label: "Software Engineering", icon: Code2, className: "border-slate-400/25 bg-slate-400/10 text-slate-300" },
  general: { label: "General", icon: BriefcaseBusiness, className: "border-border bg-[#fff8f1] text-[#4a4a47]" },
} as const;

type JobRoleCategory = keyof typeof jobRoleVisuals;

const jobSourceBadges: Record<
  Job["logo"],
  { label: string; text: string; className: string }
> = {
  linkedin: { label: "LinkedIn", text: "in", className: "bg-[#0a66c2] text-foreground" },
  indeed: { label: "Indeed", text: "indeed", className: "bg-white text-[#2557a7] tracking-[-0.08em]" },
  jobs_ch: { label: "jobs.ch", text: "jobs.ch", className: "bg-white text-[#fa5d00] tracking-[-0.08em]" },
  company: { label: "Direct company", text: "DC", className: "bg-[#fa5d00] text-foreground tracking-[-0.04em]" },
  manual: { label: "Manually added", text: "+", className: "bg-[#fff8f1] text-[#1d1e1c]" },
  figma: { label: "Figma", text: "F", className: "bg-black text-foreground" },
  stripe: { label: "Stripe", text: "S", className: "bg-[#635bff] text-foreground" },
};

export function getJobSourceLabel(job: Job) {
  return getDirectCompanyByJobId(job.id)?.name ?? jobSourceBadges[job.logo].label;
}

function getSpecializedJobRoleCategory(value: string): JobRoleCategory | null {
  const text = value.toLowerCase();
  const has = (...keywords: string[]) =>
    keywords.some((keyword) => text.includes(keyword));

  if (has("cybersecurity", "cyber security", "information security", "security engineer", "security analyst", "infosec", "soc analyst")) return "security";
  if (has("artificial intelligence", "machine learning", "deep learning", "generative ai", "genai", "llm", "computer vision", "natural language processing", "data scientist", "data science", "pytorch", "tensorflow", "ml engineer") || /(^|[^a-z])(ai|ml)([^a-z]|$)/.test(text)) return "ai";
  if (has("data analyst", "business analyst", "analytics", "business intelligence", "tableau", "power bi", "bi developer")) return "analytics";
  if (has("data engineer", "data platform", "database engineer", "data warehouse", "etl", "snowflake", "databricks", "apache spark", "kafka")) return "data";
  if (has("devops", "site reliability", "cloud engineer", "platform engineer", "infrastructure engineer", "kubernetes", "terraform", "sre")) return "devops";
  if (has("ios", "android", "mobile developer", "mobile engineer", "react native", "flutter", "swift", "kotlin")) return "mobile";
  if (has("frontend", "front-end", "front end", "web developer", "react developer", "ui engineer", "react", "vue", "angular", "next.js")) return "frontend";
  if (has("backend", "back-end", "back end", "server-side", "api engineer", "java developer", "python developer", "golang", "node.js", "spring boot", "django", "fastapi")) return "backend";
  if (has("quality assurance", "qa engineer", "test engineer", "test automation", "software tester", "sdet", "selenium", "cypress", "playwright")) return "qa";
  if (has("product design", "product designer", "ux designer", "ui designer", "interaction designer", "design lead", "design system")) return "design";
  return null;
}

function getJobRoleCategory(job: Job): JobRoleCategory {
  const titleCategory = getSpecializedJobRoleCategory(job.title);
  if (titleCategory) return titleCategory;

  const normalizedTitle = job.title.toLowerCase();
  if (
    normalizedTitle.includes("full stack") ||
    normalizedTitle.includes("full-stack")
  ) {
    return "software";
  }

  const departmentCategory = getSpecializedJobRoleCategory(job.department);
  if (departmentCategory) return departmentCategory;

  const skillsCategory = getSpecializedJobRoleCategory(job.skills.join(" "));
  if (skillsCategory) return skillsCategory;

  if (
    [
      "software engineer",
      "software developer",
      "application developer",
      "engineer",
      "developer",
    ].some((keyword) => normalizedTitle.includes(keyword))
  ) {
    return "software";
  }
  return "general";
}

export function JobRoleIcon({
  job,
  large = false,
  compact = false,
}: JobRoleIconProps) {
  const role = jobRoleVisuals[getJobRoleCategory(job)];
  const source = jobSourceBadges[job.logo];
  const directCompany = getDirectCompanyByJobId(job.id);
  const Icon = role.icon;
  const sizeClass = compact
    ? "h-9 w-9 2xl:h-11 2xl:w-11"
    : large
      ? "h-14 w-14 2xl:h-16 2xl:w-16"
      : "h-11 w-11 2xl:h-14 2xl:w-14";
  const iconSizeClass = compact
    ? "h-4 w-4 2xl:h-5 2xl:w-5"
    : large
      ? "h-7 w-7 2xl:h-8 2xl:w-8"
      : "h-5 w-5 2xl:h-6 2xl:w-6";
  const badgeSizeClass = compact
    ? "-bottom-0.5 -right-0.5 h-3.5 min-w-3.5 px-0.5 text-[6px] 2xl:h-4 2xl:min-w-4 2xl:text-[7px]"
    : large
      ? "-bottom-1 -right-1 h-5 min-w-5 px-1 text-[8px] 2xl:h-6 2xl:min-w-6 2xl:text-[9px]"
      : "-bottom-0.5 -right-0.5 h-4 min-w-4 px-0.5 text-[7px] 2xl:h-5 2xl:min-w-5 2xl:text-[8px]";

  if (directCompany) {
    const logoPaddingClass = compact
      ? "p-1.5 2xl:p-2"
      : large
        ? "p-2.5 2xl:p-3.5"
        : "p-2 2xl:p-2.5";

    return (
      <div
        title={`${directCompany.name} · Direct company`}
        className={cn(
          "grid shrink-0 place-items-center overflow-hidden rounded-lg border border-border bg-white",
          sizeClass,
          logoPaddingClass,
        )}
      >
        <Image
          src={directCompany.logoSrc}
          alt={directCompany.logoAlt}
          width={directCompany.logoWidth ?? 180}
          height={directCompany.logoHeight ?? 48}
          className="block max-h-full w-full object-contain"
        />
      </div>
    );
  }

  return (
    <div
      role="img"
      aria-label={`${role.label} role · ${source.label}`}
      title={`${role.label} · ${source.label}`}
      className={cn(
        "relative grid shrink-0 place-items-center rounded-lg border",
        role.className,
        sizeClass,
      )}
    >
      <Icon
        className={iconSizeClass}
        strokeWidth={large ? 1.7 : 1.9}
        aria-hidden="true"
      />
      <span
        aria-hidden="true"
        className={cn(
          "absolute grid place-items-center rounded border border-[#ffffff] font-black leading-none shadow-sm",
          source.className,
          badgeSizeClass,
        )}
      >
        {source.text}
      </span>
    </div>
  );
}
