declare const revisionTokenBrand: unique symbol;

export type RevisionToken = string & {
  readonly [revisionTokenBrand]: "RevisionToken";
};

export function revisionToken(value: string | number): RevisionToken {
  if (typeof value === "number") return `"${value}"` as RevisionToken;
  const normalized = value.trim();
  if (!normalized) throw new Error("Revision token cannot be empty");
  if (normalized.startsWith('"') || normalized.startsWith("W/\"")) {
    return normalized as RevisionToken;
  }
  return `"${normalized}"` as RevisionToken;
}

export function revisionFromEtag(value: string | null): RevisionToken | null {
  return value?.trim() ? revisionToken(value) : null;
}

export type Versioned<T> = {
  value: T;
  revision: RevisionToken | null;
};
