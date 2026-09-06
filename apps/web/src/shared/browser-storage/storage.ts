export const browserStorageNamespacePrefix = "rufina.";

function getStorage() {
  return typeof window === "undefined" ? null : window.localStorage;
}

export function readBrowserStorage(key: string) {
  return getStorage()?.getItem(key) ?? null;
}

export function writeBrowserStorage(key: string, value: string) {
  getStorage()?.setItem(key, value);
}

export function removeBrowserStorage(key: string) {
  getStorage()?.removeItem(key);
}

export function clearBrowserStorageNamespace(prefix: string) {
  const storage = getStorage();
  if (!storage) return;
  const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index))
    .filter((key): key is string => Boolean(key?.startsWith(prefix)));
  for (const key of keys) storage.removeItem(key);
}
