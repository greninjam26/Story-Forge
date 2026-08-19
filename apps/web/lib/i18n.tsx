"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useSyncExternalStore,
} from "react";
import { DEFAULT_LOCALE, LOCALES, messages, type Locale } from "./messages";

const STORAGE_KEY = "storyforge-locale";

const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function getSnapshot(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored && (LOCALES as string[]).includes(stored)
    ? (stored as Locale)
    : DEFAULT_LOCALE;
}

function getServerSnapshot(): Locale {
  return DEFAULT_LOCALE;
}

function persistLocale(l: Locale) {
  localStorage.setItem(STORAGE_KEY, l);
  listeners.forEach((cb) => cb());
}

type Ctx = { locale: Locale; setLocale: (l: Locale) => void };
const LocaleContext = createContext<Ctx | null>(null);

function lookup(locale: Locale, key: string): string | undefined {
  const value = key.split(".").reduce<unknown>(
    (obj, part) =>
      obj && typeof obj === "object"
        ? (obj as Record<string, unknown>)[part]
        : undefined,
    messages[locale],
  );
  return typeof value === "string" ? value : undefined;
}

function interpolate(
  str: string,
  params?: Record<string, string | number>,
): string {
  if (!params) return str;
  return str.replace(/\{(\w+)\}/g, (_, k) =>
    k in params ? String(params[k]) : `{${k}}`,
  );
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const locale = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((l: Locale) => persistLocale(l), []);

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale(): Ctx {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error("useLocale must be used within a LocaleProvider");
  return ctx;
}

export function useT() {
  const { locale } = useLocale();
  return useCallback(
    (key: string, params?: Record<string, string | number>) => {
      const raw =
        lookup(locale, key) ?? lookup(DEFAULT_LOCALE, key) ?? key;
      return interpolate(raw, params);
    },
    [locale],
  );
}
