export function isInlineDataUrl(value: unknown): boolean {
  return typeof value === "string" && value.trim().toLowerCase().startsWith("data:");
}

export function decodeDataUrl(dataUrl: string): Blob {
  const normalizedDataUrl = dataUrl.trim();
  const match = /^data:([^;,]+)?(;base64)?,(.*)$/is.exec(normalizedDataUrl);
  if (!match) throw new Error("Legacy file data is invalid");
  const contentType = match[1] || "application/octet-stream";
  const bytes = match[2]
    ? Uint8Array.from(atob(match[3]), (character) => character.charCodeAt(0))
    : new TextEncoder().encode(decodeURIComponent(match[3]));
  return new Blob([bytes], { type: contentType });
}
