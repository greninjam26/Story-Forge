"use client";

import Link from "next/link";
import { useT } from "@/lib/i18n";

export default function TermsPage() {
  const t = useT();

  return (
    <main className="mx-auto w-full max-w-lg flex-1 space-y-8 p-8">
      <Link href="/children" className="text-sm text-indigo-600">
        {t("common.back")}
      </Link>

      <h1 className="text-2xl font-semibold">{t("terms.heading")}</h1>

      <p className="text-sm text-zinc-700 dark:text-zinc-300">
        {t("terms.intro")}
      </p>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("terms.contentHeading")}</h2>
        <ul className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("terms.content1")}</li>
          <li>{t("terms.content2")}</li>
          <li>{t("terms.content3")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("terms.changesHeading")}</h2>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {t("terms.changes")}
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("terms.contactHeading")}</h2>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {t("terms.contact")}
        </p>
      </section>
    </main>
  );
}
