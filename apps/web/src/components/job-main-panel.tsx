"use client";

import type { RefObject } from "react";
import { ChevronDown } from "lucide-react";

import { AiMatchScoreSummary } from "@/components/ai-match-score-summary";
import { parseJobDescription } from "@/lib/job-description";
import { cn } from "@/lib/utils";
import type { Job } from "@/shared/types/job";

type JobMainPanelProps = {
  job: Job;
  tab: string;
  analysisRef?: RefObject<HTMLElement | null>;
};

export function JobMainPanel({
  job,
  tab,
  analysisRef,
}: JobMainPanelProps) {
  if (tab === "AI Match") {
    return (
      <article
        ref={analysisRef}
        tabIndex={-1}
        className="panel scroll-mt-4 p-3 outline-none 2xl:p-4"
      >
        <h3 className="mb-4 text-base font-bold 2xl:text-lg">AI Match Score</h3>
        <AiMatchScoreSummary job={job} />
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
