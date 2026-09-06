import { useCallback, useEffect, useState } from "react";

import { createClientId } from "@/lib/client-id";
import {
  readBrowserStorage,
  removeBrowserStorage,
  writeBrowserStorage,
} from "@/shared/browser-storage/storage";

import { appLogsStorageKey, maxStoredAppLogs } from "../model/constants";
import { normalizeStoredLogs } from "../model/normalizers";
import type { AppLogEntry } from "../model/types";

export function useActivityFeed() {
  const [entries, setEntries] = useState<AppLogEntry[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    try {
      const rawLogs = readBrowserStorage(appLogsStorageKey);
      setEntries(normalizeStoredLogs(rawLogs ? JSON.parse(rawLogs) : [], {
        createId: createClientId,
        now: () => new Date().toISOString(),
      }));
    } catch {
      removeBrowserStorage(appLogsStorageKey);
      setError(new Error("Stored activity could not be loaded"));
    } finally {
      setIsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!isLoaded) return;
    try {
      writeBrowserStorage(
        appLogsStorageKey,
        JSON.stringify(entries.slice(0, maxStoredAppLogs)),
      );
    } catch {
      setError(new Error("Activity could not be stored locally"));
    }
  }, [entries, isLoaded]);

  const append = useCallback((entry: Omit<AppLogEntry, "id" | "timestamp">) => {
    setEntries((currentEntries) => [
      {
        ...entry,
        id: createClientId("log"),
        timestamp: new Date().toISOString(),
      },
      ...currentEntries,
    ].slice(0, maxStoredAppLogs));
  }, []);

  const clear = useCallback(() => {
    setEntries([]);
    setError(null);
  }, []);

  return {
    entries,
    isLoading: !isLoaded,
    error,
    append,
    clear,
  };
}
