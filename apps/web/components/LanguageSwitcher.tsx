"use client";

import { memo } from "react";
import { useLocale, useT } from "@/lib/i18n";
import { LOCALES } from "@/lib/messages";

export const LanguageSwitcher = memo(function LanguageSwitcher() {
  const { locale, setLocale } = useLocale();
  const t = useT();

  return (
    <div
      role="group"
      aria-label={t("auth.localeLabel")}
      className="fixed top-4 right-4 z-50 flex items-center gap-1 rounded-full bg-white/80 px-3 py-1.5 text-sm shadow-sm backdrop-blur dark:bg-zinc-800/80"
    >
      {LOCALES.map((l, i) => (
        <span key={l} className="flex items-center gap-1">
          {i > 0 && <span className="text-zinc-300 dark:text-zinc-600">·</span>}
          <button
            onClick={() => setLocale(l)}
            className={`rounded-full px-2 py-0.5 transition-colors ${
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
  );
});
