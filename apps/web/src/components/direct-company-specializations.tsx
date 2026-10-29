"use client";

import { useState } from "react";
import { Check, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { directCompanySpecializationOptions } from "@/features/job-search/model/specializations";
import type { DirectCompanyDirection } from "@/features/job-search/model/types";
import { cn } from "@/lib/utils";

type DirectCompanySpecializationsProps = {
  direction: DirectCompanyDirection;
  selected: readonly string[];
  onChange: (specializations: string[]) => void;
};

export function DirectCompanySpecializations({
  direction,
  selected,
  onChange,
}: DirectCompanySpecializationsProps) {
  const [customSpecialization, setCustomSpecialization] = useState("");
  const presets = directCompanySpecializationOptions[direction];
  const selectedKeys = new Set(
    selected.map((value) => value.toLocaleLowerCase()),
  );
  const presetKeys = new Set(presets.map((value) => value.toLocaleLowerCase()));
  const options = [
    ...presets,
    ...selected.filter((value) => !presetKeys.has(value.toLocaleLowerCase())),
  ];
  const normalizedCustom = customSpecialization.trim().replace(/\s+/g, " ");
  const isDuplicate = selectedKeys.has(normalizedCustom.toLocaleLowerCase());
  const atLimit = selected.length >= 50;
  const canAdd =
    Boolean(normalizedCustom) &&
    normalizedCustom.length <= 160 &&
    !isDuplicate &&
    !atLimit;

  function addCustomSpecialization() {
    if (!canAdd) return;
    onChange([...selected, normalizedCustom]);
    setCustomSpecialization("");
  }

  return (
    <section
      aria-labelledby="direct-company-specializations-heading"
      className="mt-4 border-t border-border pt-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4
          id="direct-company-specializations-heading"
          className="text-xs font-bold text-foreground"
        >
          Specializations
          {selected.length > 0 ? (
            <span className="ml-2 rounded-full bg-accent/10 px-2 py-0.5 text-[11px] text-accent">
              {selected.length} selected
            </span>
          ) : null}
        </h4>
        <button
          type="button"
          disabled={selected.length === 0}
          onClick={() => onChange([])}
          className="text-xs font-bold text-muted transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
        >
          Clear specializations
        </button>
      </div>
      <p className="mt-1 text-xs font-medium leading-5 text-muted">
        Choose any that interest you, or add your own. No selection means all
        specializations in this direction. Changing direction clears the
        selection.
      </p>
      {options.length > 0 ? (
        <div
          role="group"
          aria-label="Direct company specializations"
          className="mt-3 flex flex-wrap gap-2"
        >
          {options.map((option) => {
            const key = option.toLocaleLowerCase();
            const active = selectedKeys.has(key);
            return (
              <button
                key={key}
                type="button"
                aria-pressed={active}
                disabled={atLimit && !active}
                onClick={() =>
                  onChange(
                    active
                      ? selected.filter(
                          (value) => value.toLocaleLowerCase() !== key,
                        )
                      : [...selected, option],
                  )
                }
                className={cn(
                  "inline-flex min-h-8 max-w-full items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
                  active
                    ? "border-accent/30 bg-accent/10 text-foreground"
                    : "border-border bg-white text-muted hover:text-foreground",
                )}
              >
                {active ? <Check className="h-3.5 w-3.5 shrink-0" /> : null}
                <span className="break-words">{option}</span>
              </button>
            );
          })}
        </div>
      ) : null}
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          aria-label="Custom direct company specialization"
          maxLength={160}
          disabled={atLimit}
          value={customSpecialization}
          onChange={(event) => setCustomSpecialization(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addCustomSpecialization();
            }
          }}
          placeholder="Add a specific profession or specialization"
          className="h-9 min-w-0 flex-1 rounded-md border border-border bg-white px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70 disabled:opacity-50"
        />
        <Button
          type="button"
          variant="ghost"
          disabled={!canAdd}
          onClick={addCustomSpecialization}
          className="h-9 rounded-md border border-border bg-white px-3 text-xs text-foreground hover:bg-[#fff3e8] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Add specialization
        </Button>
      </div>
      {atLimit ? (
        <p role="status" className="mt-2 text-xs text-muted">
          You can select up to 50 specializations.
        </p>
      ) : null}
      <p className="mt-2 text-xs font-medium leading-5 text-muted">
        A vacancy must match the direction and at least one selected
        specialization. Job titles and responsibilities are used to identify the
        role.
      </p>
    </section>
  );
}
