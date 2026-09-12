import { InfoStat } from "@/components/info-stat";
import { formatAiMatchTimestamp } from "@/features/jobs/formatting";
import {
  formatMatchValue,
  getAiMatchSourceDisplay,
} from "@/features/jobs/model/ai-match";
import type { Job } from "@/shared/types/job";

export function AiMatchScoreSummary({
  job,
  isAnalyzing = false,
}: {
  job: Job;
  isAnalyzing?: boolean;
}) {
  return (
    <div>
      <p className="mb-4 text-sm text-muted">
        Suitability of this vacancy for your master profile.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <InfoStat
          label="AI match"
          value={isAnalyzing ? "Calculating..." : formatMatchValue(job)}
        />
        <InfoStat
          label="Source"
          value={getAiMatchSourceDisplay(job)}
          title={job.aiMatch?.providerError}
        />
        <InfoStat
          label="Updated"
          value={formatAiMatchTimestamp(job.aiMatch?.updatedAt)}
        />
      </div>
      {isAnalyzing ? (
        <p className="mt-4 text-sm font-semibold text-accent" role="status">
          Calculating suitability. The score will update automatically when saved.
        </p>
      ) : null}
    </div>
  );
}
