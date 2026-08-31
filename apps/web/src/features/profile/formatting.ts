import { hasProfileValue } from "./model/normalizers";

export function displayProfileValue(value: string, fallback: string) {
  return hasProfileValue(value) ? value : fallback;
}

export function displayProfileFirstName(value: string, fallback: string) {
  return hasProfileValue(value) ? value.trim().split(/\s+/)[0] : fallback;
}

export function formatProfileDate(value: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
