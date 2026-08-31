import { normalizeJobsChJobUrl } from "@/lib/job-url";
import { normalizeExternalUrl } from "@/shared/formatting/urls";
import type { Job } from "@/shared/types/job";

export function getJobApplyUrl(job: Job) {
  const normalizedUrl = normalizeExternalUrl(job.applyUrl || job.sourceUrl || "");
  return /^https?:\/\//i.test(normalizedUrl)
    ? normalizeJobsChJobUrl(normalizedUrl)
    : "";
}

export function formatJobPosted(value: string) {
  const parsedDate = Date.parse(value);
  if (!Number.isNaN(parsedDate)) {
    return new Intl.DateTimeFormat("de-CH", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(parsedDate));
  }

  return value
    .replace(/^(\d+)h ago$/i, "$1 hours ago")
    .replace(/^(\d+)d ago$/i, "$1 days ago");
}

export function formatJobPostedCompact(value: string) {
  const parsedDate = Date.parse(value);
  if (!Number.isNaN(parsedDate)) {
    const parsedDateValue = new Date(parsedDate);
    const day = parsedDateValue.getDate().toString().padStart(2, "0");
    const month = (parsedDateValue.getMonth() + 1).toString().padStart(2, "0");
    const date = `${day}.${month}`;
    const time = new Intl.DateTimeFormat("de-CH", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(parsedDateValue);

    return `${date} • ${time}`;
  }

  return formatJobPosted(value);
}

export function formatJobLocationCompact(value: string) {
  return value.split(",")[0]?.trim() || value;
}

export function formatAiMatchTimestamp(value?: string) {
  if (!value) return "Not calculated yet";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time unknown";

  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatConfidence(value?: "low" | "medium" | "high") {
  if (!value) return "Not calculated";
  return `${value[0].toUpperCase()}${value.slice(1)}`;
}
