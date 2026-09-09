"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, getToken } from "@/lib/api";
import { useT } from "@/lib/i18n";

export default function Home() {
  const t = useT();
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    api
      .me()
      .then(() => {
        if (!cancelled) router.push("/children");
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="flex flex-1 bg-zinc-50 dark:bg-zinc-950">
      <main className="mx-auto grid w-full max-w-6xl items-center gap-12 px-4 py-12 sm:px-6 sm:py-16 lg:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)] lg:px-8">
        <section className="max-w-2xl space-y-6">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-indigo-600 dark:text-indigo-400">
            {t("navigation.brand")}
          </p>
          <h1 className="text-4xl font-semibold tracking-tight text-zinc-900 sm:text-5xl dark:text-zinc-100">
            {t("meta.title")}
          </h1>
          <p className="max-w-xl text-lg leading-8 text-zinc-600 dark:text-zinc-400">
            {t("home.tagline")}
          </p>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{t("home.loginPrompt")}</p>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/auth/register"
              className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700"
            >
              {t("auth.registerLink")}
            </Link>
            <Link
              href="/auth/login"
              className="rounded-lg border border-zinc-300 bg-white px-5 py-2.5 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              {t("auth.loginLink")}
            </Link>
          </div>
        </section>

        <section
          aria-labelledby="how-it-works"
          className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-8 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <h2 id="how-it-works" className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
            {t("home.howItWorks")}
          </h2>
          <ol className="mt-6 space-y-5">
            {["share", "create", "review"].map((step, index) => (
              <li key={step} className="flex gap-4">
                <span className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-indigo-100 text-sm font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                  {index + 1}
                </span>
                <div>
                  <h3 className="font-medium text-zinc-900 dark:text-zinc-100">
                    {t(`home.${step}Title`)}
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-zinc-600 dark:text-zinc-400">
                    {t(`home.${step}Body`)}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      </main>
    </div>
  );
}
