export function normalizeExternalUrl(value: string) {
  const trimmedValue = value.trim();

  if (!trimmedValue) return "";
  if (/^https?:\/\//i.test(trimmedValue)) return trimmedValue;
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedValue)) return `mailto:${trimmedValue}`;
  if (/^[a-z][a-z\d+\-.]*:/i.test(trimmedValue)) return "";

  return `https://${trimmedValue.replace(/^\/+/, "")}`;
}
