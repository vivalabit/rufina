"use client";

import { useEffect, useState } from "react";
import { Save, Upload, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { defaultCandidateProfile } from "@/features/profile/model/defaults";
import type { CandidateProfile } from "@/shared/types/profile";
import { cn } from "@/lib/utils";

export function ProfileEditorDialog({
  profile,
  avatarFile,
  useDefaultAvatar,
  status,
  message,
  onChange,
  onAvatarFileSelected,
  onUseDefaultAvatar,
  onClose,
  onSave,
}: {
  profile: CandidateProfile;
  avatarFile: File | null;
  useDefaultAvatar: boolean;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  onChange: <Field extends keyof CandidateProfile>(
    field: Field,
    value: CandidateProfile[Field],
  ) => void;
  onAvatarFileSelected: (file: File) => void;
  onUseDefaultAvatar: () => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const [avatarPreviewUrl, setAvatarPreviewUrl] = useState("");
  useEffect(() => {
    if (!avatarFile || typeof URL.createObjectURL !== "function") {
      setAvatarPreviewUrl("");
      return;
    }
    const previewUrl = URL.createObjectURL(avatarFile);
    setAvatarPreviewUrl(previewUrl);
    return () => URL.revokeObjectURL(previewUrl);
  }, [avatarFile]);

  const fields: Array<{
    field: keyof CandidateProfile;
    label: string;
    placeholder: string;
    type?: "input" | "textarea";
  }> = [
    { field: "name", label: "Name", placeholder: "Your full name" },
    {
      field: "current_role",
      label: "Current role",
      placeholder: "Frontend Engineer, Product Manager, Student...",
    },
    {
      field: "desired_role",
      label: "Target role",
      placeholder: "Roles you want to apply for",
    },
    {
      field: "location",
      label: "Location",
      placeholder: "City, country, timezone, or remote",
    },
    {
      field: "work_format",
      label: "Work format",
      placeholder: "Remote, hybrid, onsite, relocation",
    },
    {
      field: "headline",
      label: "Headline / summary",
      placeholder: "Short positioning statement",
      type: "textarea",
    },
    {
      field: "linkedin",
      label: "LinkedIn",
      placeholder: "linkedin.com/in/username",
    },
    { field: "github", label: "GitHub", placeholder: "github.com/username" },
    { field: "portfolio", label: "Portfolio", placeholder: "portfolio.com" },
    {
      field: "personal_site",
      label: "Personal site",
      placeholder: "your-site.com",
    },
  ];

  function handleAvatarFile(file: File | undefined) {
    if (!file) return;

    if (file.size > 1_000_000) {
      window.alert("Avatar image must be under 1MB.");
      return;
    }

    onAvatarFileSelected(file);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/72 px-3 py-4 backdrop-blur-sm">
      <div className="panel flex max-h-[calc(100vh-32px)] w-full max-w-[820px] flex-col overflow-hidden border-border bg-[#ffffff]/96 p-4 shadow-[0_24px_70px_rgba(0,0,0,0.52)] sm:p-5">
        <div className="flex shrink-0 items-start justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-bold leading-tight text-foreground 2xl:text-[24px]">
              Edit Profile
            </h2>
            <p className="mt-1 text-sm font-medium text-muted">
              Add the details you want job matching and applications to use.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close profile editor"
            onClick={onClose}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-[#fff3e8] hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="job-scroll mt-5 min-h-0 flex-1 overflow-y-auto rounded-md border border-border p-4">
          <div className="mb-5 flex flex-col gap-4 rounded-md border border-border bg-[#fff8f1] p-4 sm:flex-row sm:items-center">
            <img
              src={
                useDefaultAvatar
                  ? defaultCandidateProfile.avatar_url
                  : avatarPreviewUrl ||
                    profile.avatar_url ||
                    defaultCandidateProfile.avatar_url
              }
              alt=""
              className="h-20 w-20 shrink-0 rounded-full object-cover ring-1 ring-white/10"
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-foreground">Avatar</p>
              <p className="mt-1 text-xs leading-5 text-muted">
                Default is the pug image. Upload PNG, JPG, or WebP under 1MB.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <label className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-md border border-border bg-[#fff8f1] px-3 text-xs font-semibold text-[#1d1e1c] transition hover:bg-[#fff3e8]">
                  <Upload className="h-4 w-4" />
                  Change Avatar
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="hidden"
                    onChange={(event) =>
                      handleAvatarFile(event.target.files?.[0])
                    }
                  />
                </label>
                <button
                  type="button"
                  className="inline-flex h-9 items-center justify-center rounded-md border border-border bg-transparent px-3 text-xs font-semibold text-[#1d1e1c] transition hover:bg-[#fff3e8]"
                  onClick={onUseDefaultAvatar}
                >
                  Use Default
                </button>
              </div>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {fields.map((item) => (
              <label
                key={item.field}
                className={cn(
                  "grid gap-2",
                  item.type === "textarea" && "md:col-span-2",
                )}
              >
                <span className="text-xs font-bold text-[#1d1e1c]">
                  {item.label}
                </span>
                {item.type === "textarea" ? (
                  <textarea
                    value={profile[item.field]}
                    onChange={(event) =>
                      onChange(item.field, event.target.value)
                    }
                    placeholder={item.placeholder}
                    rows={4}
                    className="min-h-[112px] resize-none rounded-md border border-border bg-[#ffffff] px-3 py-2.5 text-sm font-semibold leading-5 text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
                  />
                ) : (
                  <input
                    value={profile[item.field]}
                    onChange={(event) =>
                      onChange(item.field, event.target.value)
                    }
                    placeholder={item.placeholder}
                    className="h-10 rounded-md border border-border bg-[#ffffff] px-3 text-sm font-semibold text-foreground outline-none placeholder:text-muted/70 focus:border-accent/70"
                  />
                )}
              </label>
            ))}
          </div>
        </div>

        <div className="mt-4 flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p
            className={cn(
              "text-sm font-semibold",
              status === "error" ? "text-[#fa5d00]" : "text-muted",
            )}
          >
            {message || "Empty fields stay hidden on the profile page"}
          </p>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              className="h-10 rounded-md border border-border bg-transparent px-6 text-[13px] text-[#1d1e1c] hover:bg-[#fff3e8]"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              className="h-10 rounded-md bg-gradient-to-r from-[#fa5d00] to-[#df4f00] px-7 text-[13px] text-foreground shadow-[0_12px_28px_rgba(255,90,0,0.25)] hover:from-[#e95300] hover:to-[#e95300]"
              disabled={status === "loading"}
              onClick={onSave}
            >
              <Save className="h-4 w-4" />
              {status === "loading" ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
