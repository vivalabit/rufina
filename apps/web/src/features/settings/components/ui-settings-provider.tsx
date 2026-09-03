"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { uiSettingsStorageKey } from "../browser-storage/keys";
import { defaultUiSettings } from "../model/defaults";
import type { UiSettings } from "../model/types";

type UiSettingsContextValue = {
  settings: UiSettings;
  isLoading: boolean;
  updateSettings: (update: Partial<UiSettings>) => void;
};

const UiSettingsContext = createContext<UiSettingsContextValue | null>(null);

export function UiSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<UiSettings>(defaultUiSettings);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    try {
      const rawSettings = window.localStorage.getItem(uiSettingsStorageKey);
      const storedSettings = rawSettings
        ? JSON.parse(rawSettings) as Partial<UiSettings>
        : {};
      setSettings({ ...defaultUiSettings, ...storedSettings });
    } catch {
      window.localStorage.removeItem(uiSettingsStorageKey);
    } finally {
      setIsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!isLoaded) return;
    window.localStorage.setItem(uiSettingsStorageKey, JSON.stringify(settings));
  }, [isLoaded, settings]);

  const value = useMemo<UiSettingsContextValue>(() => ({
    settings,
    isLoading: !isLoaded,
    updateSettings(update) {
      setSettings((current) => ({ ...current, ...update }));
    },
  }), [isLoaded, settings]);

  return (
    <UiSettingsContext.Provider value={value}>
      {children}
    </UiSettingsContext.Provider>
  );
}

export function useUiSettings() {
  const context = useContext(UiSettingsContext);
  if (!context) {
    throw new Error("useUiSettings must be used inside UiSettingsProvider");
  }
  return context;
}
