import type { TrackedApplication } from "@/shared/types/application";

export function applicationPayloadForStorage(
  application: TrackedApplication,
) {
  const payload: Partial<TrackedApplication> = { ...application };
  delete payload.documents;
  return payload;
}
