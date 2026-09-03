import { apiOwnerId } from "./config";

export function ownerQueryKey<const T extends readonly unknown[]>(key: T) {
  return ["owner", apiOwnerId, ...key] as const;
}
