"use client";

import { formatJobPosted } from "@/features/jobs/formatting";
import {
  formatMatchValue,
  getDisplayMatch,
} from "@/features/jobs/model/ai-match";
import type { Job } from "@/shared/types/job";

type MatchPanelProps = {
  job: Job;
  onReviewFullAnalysis: () => void;
};

export function MatchPanel({
  job,
  onReviewFullAnalysis,
}: MatchPanelProps) {
  return (
    <article className="panel p-4 2xl:p-5">
      <h3 className="text-base font-bold 2xl:text-lg">AI Match Score</h3>
      <p className="mt-3 text-[34px] font-bold leading-none text-success 2xl:mt-4 2xl:text-[40px]">
        {formatMatchValue(job)}
      </p>
      <div className="mt-2.5 h-2 rounded-full bg-[#fff8f1] 2xl:mt-3">
        <div
          className="h-full rounded-full bg-success"
          style={{ width: `${getDisplayMatch(job)}%` }}
        />
      </div>
      <button
        type="button"
        className="mt-4 inline-flex items-center gap-2 text-[13px] font-bold text-accent transition hover:text-accent/85 2xl:mt-5 2xl:text-sm"
        onClick={onReviewFullAnalysis}
      >
        View score details <span aria-hidden="true">-&gt;</span>
      </button>
    </article>
  );
}

export function SalaryInsights({ job }: { job: Job }) {
  return (
    <article className="panel p-3 2xl:p-4">
      <h3 className="text-base font-bold 2xl:text-lg">Salary Insights</h3>
      <p className="mt-4 text-[26px] font-bold leading-none 2xl:mt-6 2xl:text-[30px]">
        {job.salaryAverage}
      </p>
      <p className="mt-1.5 text-[13px] text-muted 2xl:mt-2 2xl:text-sm">
        Average total compensation
      </p>
      <div className="mt-6 2xl:mt-8">
        <div className="relative h-2 rounded-full bg-[#fff8f1]">
          <div className="absolute left-0 top-0 h-full w-1/2 rounded-full bg-accent" />
          <span className="absolute left-1/2 top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent" />
        </div>
        <div className="mt-3 flex justify-between text-[13px] font-semibold text-muted 2xl:mt-4 2xl:text-sm">
          <span>{job.salaryMin}</span>
          <span>{job.salaryAverage}</span>
          <span>{job.salaryMax}</span>
        </div>
      </div>
    </article>
  );
}

export function JobDetails({ job }: { job: Job }) {
  const details = [
    ["Posted", formatJobPosted(job.posted)],
    ["Job Type", job.type],
    ["Experience", job.experience],
    ["Location", job.location],
    ["Department", job.department],
  ];

  return (
    <article className="panel p-4 2xl:p-5">
      <h3 className="text-base font-bold 2xl:text-lg">Job Details</h3>
      <dl className="mt-4 space-y-2.5 2xl:mt-5 2xl:space-y-3">
        {details.map(([label, value]) => (
          <div
            key={label}
            className="grid grid-cols-[112px_1fr] gap-3 text-[13px] 2xl:grid-cols-[130px_1fr] 2xl:gap-4 2xl:text-sm"
          >
            <dt className="text-muted">{label}</dt>
            <dd className="font-semibold text-[#1d1e1c]">{value}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}
