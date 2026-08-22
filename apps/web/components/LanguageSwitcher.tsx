"use client";

import { memo, useState } from "react";
import { changeAccountLocale } from "@/lib/auth-session";
import { useLocale, useT } from "@/lib/i18n";
import { LOCALES } from "@/lib/messages";

export const LanguageSwitcher = memo(function LanguageSwitcher() {
  const { locale, setLocale } = useLocale();
  const t = useT();
  const [isSaving, setIsSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  async function handleLocaleChange(nextLocale: typeof locale) {
    if (nextLocale === locale || isSaving) return;
    setIsSaving(true);
    setSaveFailed(false);
    const changed = await changeAccountLocale(nextLocale, setLocale);
    setSaveFailed(!changed);
    setIsSaving(false);
  }

  return (
    <div
      className="fixed top-4 right-4 z-50 flex flex-col items-end text-sm"
    >
      <div
        role="group"
        aria-label={t("auth.localeLabel")}
        aria-busy={isSaving}
        className="flex items-center gap-1 rounded-full bg-white/80 px-3 py-1.5 shadow-sm backdrop-blur dark:bg-zinc-800/80"
      >
        {LOCALES.map((l, i) => (
          <span key={l} className="flex items-center gap-1">
            {i > 0 && <span className="text-zinc-300 dark:text-zinc-600">·</span>}
            <button
              onClick={() => void handleLocaleChange(l)}
              disabled={isSaving}
              className={`rounded-full px-2 py-0.5 transition-colors disabled:cursor-wait disabled:opacity-60 ${
                locale === l
                  ? "font-semibold text-indigo-600"
                  : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
              aria-pressed={locale === l}
              aria-label={t(`langSwitch.${l}`)}
            >
              {l === "en" ? "EN" : "FR"}
            </button>
          </span>
        ))}
      </div>
      {saveFailed && (
        <p
          role="alert"
          className="mt-1 max-w-64 rounded-lg bg-red-50 px-2 py-1 text-right text-xs text-red-700 shadow-sm dark:bg-red-950 dark:text-red-200"
        >
          {t("auth.localeSaveFailed")}
        </p>
      )}
    </div>
  );
});
