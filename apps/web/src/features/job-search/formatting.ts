import {
  normalizeDirectCompanyIds,
  normalizeParserIds,
} from "@/features/job-search/model/form-mappers";
import type { ParserSearchForm } from "@/features/job-search/model/types";
import { directCompanyCatalog } from "@/lib/direct-company-catalog";

export function getParserLabel(parser: string | undefined) {
  if (parser === "indeed") return "Indeed";
  if (parser === "jobs_ch" || parser === "jobs.ch") return "jobs.ch";
  if (!parser || parser === "linkedin") return "LinkedIn";
  return (
    directCompanyCatalog.find((company) => company.id === parser)?.name ??
    parser
  );
}

export function getSearchSourcesLabel(form: ParserSearchForm) {
  const sources = normalizeParserIds(form).map(getParserLabel);
  if (form.directCompaniesEnabled) {
    sources.push(
      `Direct companies (${normalizeDirectCompanyIds(form.directCompanyIds).length})`,
    );
  }
  return sources.join(" + ");
}

export function getSearchIssuesLabel(sourceErrors: Record<string, string>) {
  const failed: string[] = [];
  const partial: string[] = [];
  for (const [source, error] of Object.entries(sourceErrors)) {
    (error.startsWith("Parser returned partial results: ") ? partial : failed)
      .push(getParserLabel(source));
  }
  return [
    failed.length ? `Failed (${failed.length}): ${failed.join(", ")}` : "",
    partial.length ? `Partial (${partial.length}): ${partial.join(", ")}` : "",
  ].filter(Boolean).join("; ");
}
