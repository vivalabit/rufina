"use client";

import { Building2, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type DirectCompanyTarget = {
  id: string;
  name: string;
  careersUrl: string;
  enabled: boolean;
};

type DirectCompaniesSourceProps = {
  companies: DirectCompanyTarget[];
  onAdd: () => void;
  onChange: (
    companyId: string,
    field: "name" | "careersUrl" | "enabled",
    value: string | boolean,
  ) => void;
  onRemove: (companyId: string) => void;
};

export function DirectCompaniesSource({
  companies,
  onAdd,
  onChange,
  onRemove,
}: DirectCompaniesSourceProps) {
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
                Setup only
              </span>
            </div>
            <p className="mt-1 text-xs font-medium leading-5 text-muted">
              Save official careers pages now. Collection starts after a company parser is connected.
            </p>
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          className="h-8 shrink-0 rounded-md border border-[#8b5cf6]/45 bg-[#8b5cf6]/10 px-3 text-xs font-bold text-[#e8e0ff] hover:bg-[#8b5cf6]/20"
          onClick={onAdd}
        >
          <Plus className="h-3.5 w-3.5" />
          Add company
        </Button>
      </div>

      <div className="mt-3 grid gap-3">
        {companies.map((company, index) => (
          <div
            key={company.id}
            className="rounded-md border border-white/[0.10] bg-[#0d131a]/80 p-3"
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-muted">
                Company {index + 1}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  role="switch"
                  aria-checked={company.enabled}
                  aria-label={`Track company ${index + 1}`}
                  onClick={() =>
                    onChange(company.id, "enabled", !company.enabled)
                  }
                  className={cn(
                    "relative h-5 w-9 rounded-full transition",
                    company.enabled
                      ? "bg-[#8b5cf6] shadow-[0_0_14px_rgba(139,92,246,0.24)]"
                      : "bg-white/15",
                  )}
                >
                  <span
                    className={cn(
                      "absolute top-0.5 h-4 w-4 rounded-full bg-white transition",
                      company.enabled ? "right-0.5" : "left-0.5",
                    )}
                  />
                </button>
                <span className="text-[11px] font-semibold text-[#cbd2dc]">
                  {company.enabled ? "Tracking" : "Paused"}
                </span>
                <button
                  type="button"
                  aria-label={`Remove company ${index + 1}`}
                  className="grid h-7 w-7 place-items-center rounded text-muted transition hover:bg-[#d94d4d]/15 hover:text-[#ff7777]"
                  onClick={() => onRemove(company.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-[minmax(150px,0.72fr)_minmax(0,1.28fr)]">
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Company name</span>
                <input
                  value={company.name}
                  onChange={(event) =>
                    onChange(company.id, "name", event.target.value)
                  }
                  placeholder="e.g. Acme"
                  className="h-9 rounded-md border border-border bg-[#0a1017] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/65 focus:border-[#8b5cf6]/80"
                />
              </label>
              <label className="grid gap-2">
                <span className="text-xs font-bold text-[#d8dee8]">Careers page URL</span>
                <input
                  type="url"
                  inputMode="url"
                  value={company.careersUrl}
                  onChange={(event) =>
                    onChange(company.id, "careersUrl", event.target.value)
                  }
                  placeholder="https://company.com/careers"
                  className="h-9 rounded-md border border-border bg-[#0a1017] px-3 text-sm font-semibold text-white outline-none placeholder:text-muted/65 focus:border-[#8b5cf6]/80"
                />
              </label>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
