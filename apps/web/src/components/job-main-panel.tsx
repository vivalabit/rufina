"use client";

import type { RefObject } from "react";
import { Check, ChevronDown, CircleDot, Sparkles } from "lucide-react";

import { InfoStat } from "@/components/info-stat";
import {
  formatAiMatchTimestamp,
  formatConfidence,
} from "@/features/jobs/formatting";
import {
  buildAiMatchRawExplanation,
  buildRecommendationPlan,
  formatMatchValue,
  getAiMatchBreakdownItems,
  getAiMatchSourceDisplay,
  getProfileImprovementItems,
} from "@/features/jobs/model/ai-match";
import { parseJobDescription } from "@/lib/job-description";
import { cn } from "@/lib/utils";
import type { Job } from "@/shared/types/job";

type JobMainPanelProps = {
  job: Job;
  tab: string;
  analysisRef?: RefObject<HTMLElement | null>;
  recommendationsRef?: RefObject<HTMLElement | null>;
};

export function JobMainPanel({
  job,
  tab,
  analysisRef,
  recommendationsRef,
}: JobMainPanelProps) {
  if (tab === "AI Match") {
    const breakdownItems = getAiMatchBreakdownItems(job);
    const reasons = job.aiMatch?.reasons.length
      ? job.aiMatch.reasons
      : ["Run AI matching to generate role-specific reasons."];
    const gaps = job.aiMatch?.gaps.length
      ? job.aiMatch.gaps
      : ["No gaps have been calculated yet."];
    const sourceDisplay = getAiMatchSourceDisplay(job);
    const rawExplanation = buildAiMatchRawExplanation(job);
    const profileImprovements = getProfileImprovementItems(job);
    const recommendationPlan = buildRecommendationPlan(job);

    return (
      <article
        ref={analysisRef}
        tabIndex={-1}
        className="panel scroll-mt-4 p-3 outline-none 2xl:p-4"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-bold 2xl:text-lg">AI Match Analysis</h3>
            <p
              className="mt-1 text-xs font-semibold text-muted 2xl:text-sm"
              title={job.aiMatch?.providerError}
            >
              {sourceDisplay}
              {job.aiMatch?.confidence ? ` · ${job.aiMatch.confidence}` : ""}
              {" · "}
              {formatAiMatchTimestamp(job.aiMatch?.updatedAt)}
            </p>
          </div>
          <p className="text-2xl font-bold leading-none text-success 2xl:text-3xl">
            {formatMatchValue(job)}
          </p>
        </div>

        <div className="mt-4 grid gap-2 sm:grid-cols-3 2xl:mt-5 2xl:gap-3">
          <InfoStat label="Overall score" value={formatMatchValue(job)} />
          <InfoStat
            label="Source"
            value={sourceDisplay}
            title={job.aiMatch?.providerError}
          />
          <InfoStat
            label="Confidence"
            value={formatConfidence(job.aiMatch?.confidence)}
          />
        </div>

        <div className="mt-5 space-y-2.5 2xl:mt-6 2xl:space-y-3">
          {breakdownItems.map((item) => (
            <div
              key={item.key}
              className="grid grid-cols-[minmax(92px,0.36fr)_minmax(0,1fr)_54px] items-center gap-3"
            >
              <span className="text-[13px] font-semibold text-muted 2xl:text-sm">
                {item.label}
              </span>
              <div className="h-2 flex-1 rounded-full bg-[#fff8f1]">
                <div
                  className="h-full rounded-full bg-success"
                  style={{ width: `${item.progress}%` }}
                />
              </div>
              <span className="text-right text-[12px] font-bold text-[#1d1e1c] 2xl:text-sm">
                {item.value}/{item.max}
              </span>
            </div>
          ))}
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2 2xl:mt-6">
          <div>
            <h4 className="text-[13px] font-bold 2xl:text-sm">Reasons</h4>
            <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:space-y-2 2xl:text-sm">
              {reasons.map((item) => (
                <li key={item} className="flex gap-2">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="text-[13px] font-bold 2xl:text-sm">Gaps</h4>
            <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:space-y-2 2xl:text-sm">
              {gaps.map((item) => (
                <li key={item} className="flex gap-2">
                  <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-[#fa5d00]" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-5 grid gap-4 border-t border-border pt-5 md:grid-cols-2 2xl:mt-6 2xl:pt-6">
          <section>
            <h4 className="text-[13px] font-bold 2xl:text-sm">
              Raw Openclaw/local explanation
            </h4>
            <p className="mt-2.5 rounded-md border border-border bg-[#fff8f1] p-3 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6">
              {rawExplanation}
            </p>
          </section>
          <section>
            <h4 className="text-[13px] font-bold 2xl:text-sm">
              Source-backed application advice
            </h4>
            {profileImprovements.length ? (
              <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:space-y-2 2xl:text-sm">
                {profileImprovements.map((item) => (
                  <li key={item} className="flex gap-2">
                    <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                    {item}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2.5 text-[13px] leading-5 text-muted 2xl:text-sm">
                No source-backed profile improvements are available.
              </p>
            )}
          </section>
        </div>

        <section
          ref={recommendationsRef}
          tabIndex={-1}
          className="mt-5 scroll-mt-4 border-t border-border pt-5 outline-none 2xl:mt-6 2xl:pt-6"
        >
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h4 className="text-[15px] font-bold 2xl:text-base">
                Recommendations
              </h4>
              <p className="mt-1 text-[12px] font-semibold text-muted 2xl:text-[13px]">
                Action plan for this vacancy
              </p>
            </div>
            <p className="text-[12px] font-bold text-success 2xl:text-[13px]">
              {recommendationPlan.length} actions
            </p>
          </div>
          <div className="mt-3 divide-y divide-border">
            {recommendationPlan.length ? (
              recommendationPlan.map((recommendation) => (
                <div
                  key={`${recommendation.text}-${recommendation.gain}`}
                  className="grid gap-2 py-3 text-[13px] leading-5 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)_auto] md:items-start 2xl:text-sm"
                >
                  <div>
                    <p className="font-bold text-[#1d1e1c]">
                      {recommendation.text}
                    </p>
                    <p className="mt-1 text-muted">{recommendation.action}</p>
                  </div>
                  <p className="text-muted">{recommendation.why}</p>
                  <div className="md:text-right">
                    <p className="font-bold text-success">
                      {recommendation.gain}
                    </p>
                    <p className="mt-1 max-w-[220px] text-[12px] font-semibold text-muted md:ml-auto">
                      {recommendation.impact}
                    </p>
                  </div>
                </div>
              ))
            ) : (
              <p className="py-3 text-[13px] leading-5 text-muted 2xl:text-sm">
                No source-backed recommendations are available. Refresh AI
                Match after adding profile evidence.
              </p>
            )}
          </div>
        </section>
      </article>
    );
  }

  if (tab === "Reviews") {
    return (
      <article className="panel p-3 2xl:p-4">
        <h3 className="text-base font-bold 2xl:text-lg">Reviews</h3>
        <div className="mt-3 space-y-2.5 2xl:mt-4 2xl:space-y-3">
          {job.reviews.map((review) => (
            <p
              key={review}
              className="rounded-md border border-border bg-[#fff8f1] p-3 text-[13px] leading-5 text-muted 2xl:text-sm 2xl:leading-6"
            >
              {review}
            </p>
          ))}
        </div>
      </article>
    );
  }

  if (tab === "Similar Jobs") {
    return (
      <article className="panel p-3 2xl:p-4">
        <h3 className="text-base font-bold 2xl:text-lg">Similar Jobs</h3>
        <div className="mt-3 space-y-2.5 2xl:mt-4 2xl:space-y-3">
          {job.similarJobs.map((similarJob) => (
            <div
              key={similarJob}
              className="flex items-center justify-between rounded-md border border-border bg-[#fff8f1] p-3"
            >
              <p className="text-[13px] font-semibold text-[#1d1e1c] 2xl:text-sm">
                {similarJob}
              </p>
              <ChevronDown className="h-4 w-4 -rotate-90 text-muted" />
            </div>
          ))}
        </div>
      </article>
    );
  }

  const descriptionSections = parseJobDescription(job.overview);

  return (
    <article className="panel p-3 2xl:p-4">
      <h3 className="text-base font-bold 2xl:text-lg">Job Description</h3>
      <div className="mt-3 max-w-[78ch] space-y-5 2xl:mt-4 2xl:space-y-6">
        {descriptionSections.map((section, sectionIndex) => (
          <section key={`${section.heading ?? "overview"}-${sectionIndex}`}>
            {section.heading ? (
              <h4 className="border-l-2 border-accent pl-3 text-[13px] font-bold leading-5 text-foreground 2xl:text-sm 2xl:leading-6">
                {section.heading}
              </h4>
            ) : null}

            {section.paragraphs.length > 0 ? (
              <div
                className={cn(
                  "space-y-3",
                  section.heading && "mt-2.5 2xl:mt-3",
                )}
              >
                {section.paragraphs.map((paragraph, paragraphIndex) => (
                  <p
                    key={paragraphIndex}
                    className="text-[13px] leading-6 text-muted 2xl:text-sm 2xl:leading-7"
                  >
                    {paragraph}
                  </p>
                ))}
              </div>
            ) : null}

            {section.items.length > 0 ? (
              <ul
                className={cn(
                  "space-y-2.5",
                  section.heading && "mt-2.5 2xl:mt-3",
                )}
              >
                {section.items.map((item, itemIndex) => (
                  <li
                    key={itemIndex}
                    className="flex gap-3 text-[13px] leading-6 text-muted 2xl:text-sm 2xl:leading-7"
                  >
                    <span
                      className="mt-[0.65rem] h-1.5 w-1.5 shrink-0 rounded-full bg-accent/75"
                      aria-hidden="true"
                    />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        ))}
      </div>

      <h4 className="mt-5 text-sm font-bold 2xl:mt-7 2xl:text-base">
        Key Responsibilities
      </h4>
      <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:mt-3 2xl:space-y-2 2xl:text-sm">
        {job.responsibilities.map((item) => (
          <li key={item} className="flex gap-2">
            <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted" />
            {item}
          </li>
        ))}
      </ul>

      <h4 className="mt-5 text-sm font-bold 2xl:mt-7 2xl:text-base">
        Requirements
      </h4>
      <ul className="mt-2.5 space-y-1.5 text-[13px] leading-5 text-muted 2xl:mt-3 2xl:space-y-2 2xl:text-sm">
        {job.requirements.map((item) => (
          <li key={item} className="flex gap-2">
            <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted" />
            {item}
          </li>
        ))}
      </ul>

      <div className="mt-5 flex flex-wrap gap-2 2xl:mt-7">
        {job.skills.map((skill) => (
          <span key={skill} className="tag font-semibold">
            {skill}
          </span>
        ))}
      </div>
    </article>
  );
}
