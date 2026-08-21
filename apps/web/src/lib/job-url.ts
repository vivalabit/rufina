export function normalizeJobsChJobUrl(value: string) {
  const trimmedValue = value.trim();
  if (!trimmedValue) return "";

  try {
    const url = new URL(trimmedValue);
    const hostname = url.hostname.toLowerCase();
    if (hostname !== "jobs.ch" && !hostname.endsWith(".jobs.ch")) {
      return trimmedValue;
    }

    const normalizedPath = url.pathname.replace(/\/apply\/?$/i, "/");
    if (normalizedPath === url.pathname) return trimmedValue;

    url.pathname = normalizedPath;
    return url.toString();
  } catch {
    return trimmedValue;
  }
}
