"use client";

import Link from "next/link";
import { useT } from "@/lib/i18n";

export default function PrivacyPage() {
  const t = useT();

  return (
    <main className="mx-auto w-full max-w-lg flex-1 space-y-8 p-8">
      <Link href="/children" className="text-sm text-indigo-600">
        {t("common.back")}
      </Link>

      <h1 className="text-2xl font-semibold">{t("privacy.heading")}</h1>

      <p className="text-sm text-zinc-700 dark:text-zinc-300">
        {t("privacy.intro")}
      </p>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.collectHeading")}</h2>
        <ul className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("privacy.collectParent")}</li>
          <li>{t("privacy.collectChild")}</li>
          <li>{t("privacy.collectEvent")}</li>
          <li>{t("privacy.collectContent")}</li>
          <li>{t("privacy.collectAnalytics")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.controlHeading")}</h2>
        <ul className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("privacy.control1")}</li>
          <li>{t("privacy.control2")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.contactHeading")}</h2>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {t("privacy.contact")}
        </p>
      </section>
    </main>
  );
}
