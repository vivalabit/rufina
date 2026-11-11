"use client";

import { Plus, Trash2, X } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { createClientId } from "@/lib/client-id";
import type { ExperienceEntry, WorkProject } from "@/shared/types/profile";

export type WorkDetailBlock = "stack" | "responsibilities" | "projects";

const inputStyle = "w-full rounded-md border border-border bg-white px-3 py-2 text-sm font-semibold text-foreground outline-none focus:border-accent/70";
const cardStyle = "rounded-md border border-border bg-[#fff8f1] p-3";

function DetailField({ label, value, multiline, onChange }: {
  label: string; value?: string; multiline?: boolean; onChange: (value: string) => void;
}) {
  return <label className="grid gap-2">
    <span className="text-xs font-bold text-foreground">{label}</span>
    {multiline
      ? <textarea rows={3} className={inputStyle} value={value ?? ""} onChange={(event) => onChange(event.target.value)} />
      : <input className={inputStyle} value={value ?? ""} onChange={(event) => onChange(event.target.value)} />}
  </label>;
}

function RemoveDetail({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" aria-label={label} onClick={onClick}
    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted hover:bg-white hover:text-foreground">
    <Trash2 className="h-4 w-4" />
  </button>;
}

const projectFields: Array<[keyof Omit<WorkProject, "id" | "source_ids" | "evidence_ids">, string]> = [
  ["name", "Project name"], ["description", "Project description"], ["project_type", "Project type"],
  ["team", "Team"], ["systems", "Systems"], ["users", "Users"], ["load", "Load / scale"],
];

export function ExperienceDetailsEditor({ experience, onChange }: {
  experience: Pick<ExperienceEntry, WorkDetailBlock>;
  onChange: <Field extends WorkDetailBlock>(field: Field, value: ExperienceEntry[Field]) => void;
}) {
  const technologyInputId = useId();
  const [technologyDraft, setTechnologyDraft] = useState("");
  const stack = experience.stack ?? [];
  const responsibilities = experience.responsibilities ?? [];
  const projects = experience.projects ?? [];

  function addTechnologies() {
    const existing = new Set(stack.map((item) => item.technology.trim().toLowerCase()));
    const additions = technologyDraft.split(/[,\n]/).map((value) => value.trim()).filter((technology) => {
      if (!technology || existing.has(technology.toLowerCase())) return false;
      existing.add(technology.toLowerCase());
      return true;
    });
    if (additions.length) {
      onChange("stack", [...stack, ...additions.map((technology) => ({
        id: createClientId("technology"), technology, context: "",
      }))]);
    }
    setTechnologyDraft("");
  }

  return <div className="mt-5 grid gap-5">
    <section aria-label="Stack" className="grid gap-2">
      <label htmlFor={technologyInputId} className="text-sm font-bold text-foreground">Stack</label>
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-white px-3 py-2 focus-within:border-accent/70">
        {stack.map((item) => <span key={item.id} className="inline-flex max-w-full items-center gap-1 rounded-md bg-[#fff3e8] py-1 pl-2.5 pr-1 text-sm font-semibold text-foreground">
          <span className="min-w-0 break-words">{item.technology}</span>
          <button type="button" aria-label={`Remove ${item.technology}`}
            onClick={() => onChange("stack", stack.filter((old) => old.id !== item.id))}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted hover:bg-white hover:text-foreground">
            <X className="h-3.5 w-3.5" />
          </button>
        </span>)}
        <input id={technologyInputId} value={technologyDraft}
          onChange={(event) => setTechnologyDraft(event.target.value)}
          onBlur={addTechnologies}
          onKeyDown={(event) => {
            if (!event.nativeEvent.isComposing && (event.key === "Enter" || event.key === ",")) {
              event.preventDefault();
              addTechnologies();
            }
          }}
          placeholder="e.g. Python, React, PostgreSQL"
          aria-describedby={`${technologyInputId}-hint`}
          className="min-w-0 flex-[1_1_240px] bg-transparent py-1 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70" />
      </div>
      <p id={`${technologyInputId}-hint`} className="text-xs text-muted">Press Enter or comma to add a technology.</p>
    </section>
    <section aria-label="Responsibilities" className="grid gap-3">
      <h3 className="text-sm font-bold text-foreground">Responsibilities</h3>
      {responsibilities.map((item, index) => <fieldset key={item.id} className={cardStyle}>
        <legend className="sr-only">Responsibility {index + 1}</legend>
        <div className="flex items-start gap-3">
          <div className="grid flex-1 gap-3">
            <DetailField label="Area of responsibility" value={item.responsibility} multiline
              onChange={(responsibility) => onChange("responsibilities", responsibilities.map((old) => old.id === item.id ? { ...old, responsibility } : old))} />
            <DetailField label="Decisions" value={item.decisions} multiline
              onChange={(decisions) => onChange("responsibilities", responsibilities.map((old) => old.id === item.id ? { ...old, decisions } : old))} />
          </div>
          <RemoveDetail label={`Remove responsibility ${index + 1}`} onClick={() => onChange("responsibilities", responsibilities.filter((old) => old.id !== item.id))} />
        </div>
      </fieldset>)}
      <Button type="button" variant="outline" className="justify-self-start" onClick={() => onChange("responsibilities", [...responsibilities, { id: createClientId("responsibility"), responsibility: "", decisions: "" }])}>
        <Plus className="h-4 w-4" /> Add responsibility
      </Button>
    </section>
    <section aria-label="Work projects" className="grid gap-3">
      <h3 className="text-sm font-bold text-foreground">Projects</h3>
      {projects.map((item, index) => <div key={item.id} className={`${cardStyle} flex items-start gap-3`}>
        <details open className="min-w-0 flex-1">
          <summary className="cursor-pointer text-sm font-bold text-foreground">{item.name || `Project ${index + 1}`}</summary>
          <div className="mt-3 grid gap-3">
            {projectFields.map(([field, label]) => <DetailField key={field} label={label} value={item[field]}
              multiline={field !== "name" && field !== "project_type"}
              onChange={(value) => onChange("projects", projects.map((old) => old.id === item.id ? { ...old, [field]: value } : old))} />)}
          </div>
        </details>
        <RemoveDetail label={`Remove project ${index + 1}`} onClick={() => onChange("projects", projects.filter((old) => old.id !== item.id))} />
      </div>)}
      <Button type="button" variant="outline" className="justify-self-start" onClick={() => onChange("projects", [...projects, {
        id: createClientId("work-project"), name: "", description: "", project_type: "", team: "", systems: "", users: "", load: "",
      }])}>
        <Plus className="h-4 w-4" /> Add project
      </Button>
    </section>
  </div>;
}
