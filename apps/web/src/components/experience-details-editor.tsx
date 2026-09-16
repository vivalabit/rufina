"use client";

import { Plus, Trash2 } from "lucide-react";

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
  const stack = experience.stack ?? [];
  const responsibilities = experience.responsibilities ?? [];
  const projects = experience.projects ?? [];
  return <div className="mt-5 grid gap-5">
    <section aria-label="Stack" className="grid gap-3">
      <h3 className="text-sm font-bold text-foreground">Stack</h3>
      {stack.map((item, index) => <fieldset key={item.id} className={cardStyle}>
        <legend className="sr-only">Technology {index + 1}</legend>
        <div className="flex items-start gap-3">
          <div className="grid flex-1 gap-3 sm:grid-cols-2">
            <DetailField label="Technology" value={item.technology}
              onChange={(technology) => onChange("stack", stack.map((old) => old.id === item.id ? { ...old, technology } : old))} />
            <DetailField label="Where it was used" value={item.context} multiline
              onChange={(context) => onChange("stack", stack.map((old) => old.id === item.id ? { ...old, context } : old))} />
          </div>
          <RemoveDetail label={`Remove technology ${index + 1}`} onClick={() => onChange("stack", stack.filter((old) => old.id !== item.id))} />
        </div>
      </fieldset>)}
      <Button type="button" variant="outline" className="justify-self-start" onClick={() => onChange("stack", [...stack, { id: createClientId("technology"), technology: "", context: "" }])}>
        <Plus className="h-4 w-4" /> Add technology
      </Button>
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
