"use client";

import { useMemo, useState } from "react";
import { Building2, Check, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { DirectCompanyDefinition } from "@/lib/direct-company-catalog";

type DirectCompaniesSourceProps = {
  companies: readonly DirectCompanyDefinition[];
  selectedCompanyIds: string[];
  onSelectedCompanyIdsChange: (companyIds: string[]) => void;
};

export function DirectCompaniesSource({
  companies,
  selectedCompanyIds,
  onSelectedCompanyIdsChange,
}: DirectCompaniesSourceProps) {
  const [query, setQuery] = useState("");
  const selectedIds = useMemo(
    () => new Set(selectedCompanyIds),
    [selectedCompanyIds],
  );
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredCompanies = useMemo(
    () =>
      companies.filter((company) =>
        `${company.name} ${company.careersUrl}`
          .toLocaleLowerCase()
          .includes(normalizedQuery),
      ),
    [companies, normalizedQuery],
  );
  const allSelected =
    companies.length > 0 &&
    companies.every((company) => selectedIds.has(company.id));
  const selectedConfiguredCount = companies.filter((company) =>
    selectedIds.has(company.id),
  ).length;

  function toggleCompany(companyId: string) {
    onSelectedCompanyIdsChange(
      selectedIds.has(companyId)
        ? selectedCompanyIds.filter((id) => id !== companyId)
        : [...selectedCompanyIds, companyId],
    );
  }

  return (
    <div className="rounded-md border border-[#8b5cf6]/40 bg-[#8b5cf6]/[0.055] p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-[#6d45c8] text-white">
            <Building2 className="h-5 w-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-sm font-bold text-white">Direct company pages</h4>
              <span className="rounded bg-[#8b5cf6]/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.06em] text-[#c8b5ff]">
                {selectedConfiguredCount}/{companies.length} selected
              </span>
            </div>
            <p className="mt-1 text-xs font-medium leading-5 text-muted">
              Choose the configured companies whose official career pages you want to monitor.
            </p>
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          className="h-8 shrink-0 rounded-md border border-[#8b5cf6]/45 bg-[#8b5cf6]/10 px-3 text-xs font-bold text-[#e8e0ff] hover:bg-[#8b5cf6]/20"
          disabled={companies.length === 0}
          onClick={() =>
            onSelectedCompanyIdsChange(
              allSelected ? [] : companies.map((company) => company.id),
            )
          }
        >
          <Check className="h-3.5 w-3.5" />
          {allSelected ? "Clear all" : "Select all"}
        </Button>
      </div>

      <label className="relative mt-3 block">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search companies or career pages..."
          className="h-9 w-full rounded-md border border-border bg-[#0a1017] pl-9 pr-3 text-sm font-semibold text-white outline-none placeholder:text-muted/65 focus:border-[#8b5cf6]/80"
        />
      </label>

      {companies.length === 0 ? (
        <div className="mt-3 rounded-md border border-dashed border-white/[0.12] bg-[#0d131a]/55 px-4 py-6 text-center">
          <p className="text-sm font-bold text-[#e1e6ee]">Company catalog is empty</p>
          <p className="mt-1 text-xs font-medium leading-5 text-muted">
            Companies will appear here after they are added to the catalog with their parsers.
          </p>
        </div>
      ) : filteredCompanies.length === 0 ? (
        <div className="mt-3 rounded-md border border-dashed border-white/[0.12] bg-[#0d131a]/55 px-4 py-6 text-center">
          <p className="text-sm font-bold text-[#e1e6ee]">No companies found</p>
          <p className="mt-1 text-xs font-medium text-muted">Try another name or domain.</p>
        </div>
      ) : (
        <div className="job-scroll mt-3 grid max-h-64 gap-2 overflow-y-auto pr-1">
          {filteredCompanies.map((company) => {
            const selected = selectedIds.has(company.id);
            return (
              <label
                key={company.id}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2.5 transition",
                  selected
                    ? "border-[#8b5cf6]/70 bg-[#8b5cf6]/12"
                    : "border-white/[0.10] bg-[#0d131a]/80 hover:border-white/20 hover:bg-white/[0.045]",
                )}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => toggleCompany(company.id)}
                  className="h-4 w-4 shrink-0 accent-[#8b5cf6]"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-bold text-white">
                    {company.name}
                  </span>
                  <span className="mt-0.5 block truncate text-xs font-medium text-muted">
                    {company.careersUrl}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
