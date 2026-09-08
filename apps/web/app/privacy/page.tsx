"use client";

import Link from "next/link";
import { useT } from "@/lib/i18n";

export default function PrivacyPage() {
  const t = useT();

  return (
    <main className="mx-auto w-full max-w-lg flex-1 space-y-8 p-8">
      <Link href="/children" className="text-sm text-indigo-600 dark:text-indigo-400">
        {t("common.back")}
      </Link>

      <h1 className="text-2xl font-semibold">{t("privacy.heading")}</h1>

      <p className="text-sm text-zinc-700 dark:text-zinc-300">
        {t("privacy.intro")}
      </p>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.collectHeading")}</h2>
        <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("privacy.collectParent")}</li>
          <li>{t("privacy.collectChild")}</li>
          <li>{t("privacy.collectEvent")}</li>
          <li>{t("privacy.collectContent")}</li>
          <li>{t("privacy.collectAnalytics")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.purposesHeading")}</h2>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {t("privacy.purposes")}
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.providersHeading")}</h2>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {t("privacy.providersIntro")}
        </p>
        <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("privacy.providersStory")}</li>
          <li>{t("privacy.providersModeration")}</li>
          <li>{t("privacy.providersImages")}</li>
          <li>{t("privacy.providersNarration")}</li>
          <li>{t("privacy.providersAuthentication")}</li>
          <li>{t("privacy.providersBilling")}</li>
          <li>{t("privacy.providersInfrastructure")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.readerHeading")}</h2>
        <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("privacy.readerAccess")}</li>
          <li>{t("privacy.readerReset")}</li>
          <li>{t("privacy.readerIndexing")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.retentionHeading")}</h2>
        <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("privacy.retentionRecords")}</li>
          <li>{t("privacy.retentionBillingAudit")}</li>
          <li>{t("privacy.retentionAssets")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.controlHeading")}</h2>
        <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("privacy.control1")}</li>
          <li>{t("privacy.control2")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.deletionHeading")}</h2>
        <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("privacy.deletionControls")}</li>
          <li>{t("privacy.deletionBilling")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.analyticsHeading")}</h2>
        <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
          <li>{t("privacy.analyticsRedaction")}</li>
          <li>{t("privacy.analyticsOptOut")}</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">{t("privacy.contactHeading")}</h2>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {t("privacy.contact")} {" "}
          <a
            className="break-all text-indigo-600 underline dark:text-indigo-400"
            href={`mailto:${t("privacy.contactEmail")}`}
          >
            {t("privacy.contactEmail")}
          </a>
        </p>
        <p className="text-sm font-medium text-amber-700 dark:text-amber-300">
          {t("privacy.contactTemporary")}
        </p>
      </section>
    </main>
  );
}
