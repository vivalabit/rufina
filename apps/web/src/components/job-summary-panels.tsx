"use client";

import { Check, CircleDot } from "lucide-react";

import { formatJobPosted } from "@/features/jobs/formatting";
import {
  buildRecommendationPlan,
  formatMatchValue,
  getDisplayMatch,
  hasDisplayableMatch,
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
  const reasons = job.aiMatch?.reasons.length
    ? job.aiMatch.reasons
    : hasDisplayableMatch(job)
      ? ["Strong profile overlap", "Relevant experience", "Skills alignment"]
      : ["Run AI matching to generate role-specific reasons."];
  const gaps = job.aiMatch?.gaps ?? [];

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
      <h4 className="mt-5 text-[13px] font-bold 2xl:mt-7 2xl:text-sm">
        Why this match?
      </h4>
      <ul className="mt-2.5 space-y-1.5 text-[13px] text-muted 2xl:mt-3 2xl:space-y-2 2xl:text-sm">
        {reasons.map((item) => (
          <li key={item} className="flex items-center gap-2">
            <Check className="h-4 w-4 text-success" />
            {item}
          </li>
        ))}
      </ul>
      {gaps.length > 0 ? (
        <>
          <h4 className="mt-5 text-[13px] font-bold 2xl:mt-7 2xl:text-sm">
            Gaps
          </h4>
          <ul className="mt-2.5 space-y-1.5 text-[13px] text-muted 2xl:mt-3 2xl:space-y-2 2xl:text-sm">
            {gaps.map((item) => (
              <li key={item} className="flex items-center gap-2">
                <CircleDot className="h-4 w-4 text-[#fa5d00]" />
                {item}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <button
        type="button"
        className="mt-4 inline-flex items-center gap-2 text-[13px] font-bold text-accent transition hover:text-accent/85 2xl:mt-5 2xl:text-sm"
        onClick={onReviewFullAnalysis}
      >
        Review full analysis <span aria-hidden="true">-&gt;</span>
      </button>
    </article>
  );
}

type RecommendationsPanelProps = {
  job: Job;
  onViewAllRecommendations: () => void;
};

export function RecommendationsPanel({
  job,
  onViewAllRecommendations,
}: RecommendationsPanelProps) {
  const recommendationPlan = buildRecommendationPlan(job).slice(0, 3);

  return (
    <article className="panel p-4 2xl:p-5">
      <h3 className="text-base font-bold 2xl:text-lg">
        Evidence-backed recommendations
      </h3>
      <div className="mt-3 divide-y divide-border">
        {recommendationPlan.length ? (
          recommendationPlan.map((recommendation) => (
            <div
              key={recommendation.text}
              className="flex items-center justify-between gap-4 py-2 text-[13px] 2xl:py-2.5 2xl:text-sm"
            >
              <div>
                <p className="text-muted">{recommendation.text}</p>
                <p className="mt-1 text-[11px] font-semibold text-[#4a4a47]">
                  {recommendation.action}
                </p>
              </div>
              <p className="shrink-0 font-bold text-success">
                {recommendation.gain}
              </p>
            </div>
          ))
        ) : (
          <p className="py-3 text-[13px] leading-5 text-muted 2xl:text-sm">
            No source-backed recommendations are available.
          </p>
        )}
      </div>
      <button
        type="button"
        className="mt-3 inline-flex items-center gap-2 text-[13px] font-bold text-accent transition hover:text-accent/85 2xl:text-sm"
        onClick={onViewAllRecommendations}
      >
        View all recommendations <span aria-hidden="true">-&gt;</span>
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
