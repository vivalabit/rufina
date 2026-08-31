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
