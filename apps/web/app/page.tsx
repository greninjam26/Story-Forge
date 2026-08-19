"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, getToken } from "@/lib/api";
import { useT } from "@/lib/i18n";

export default function Home() {
  const t = useT();
  const router = useRouter();
  const [ready, setReady] = useState(() => !getToken());

  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    api
      .me()
      .then(() => {
        if (!cancelled) router.push("/children");
      })
      .catch(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (!ready) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-zinc-500">{t("common.loading")}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center bg-zinc-50 px-4 dark:bg-zinc-950">
      <main className="flex max-w-lg flex-col items-center gap-8 text-center">
        <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
          {t("meta.title")}
        </h1>
        <p className="text-lg text-zinc-600 dark:text-zinc-400">
          {t("home.tagline")}
        </p>
        <p className="text-sm text-zinc-500">{t("home.loginPrompt")}</p>
        <div className="flex gap-4">
          <Link
            href="/auth/login"
            className="rounded-md bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700"
          >
            {t("auth.loginLink")}
          </Link>
          <Link
            href="/auth/register"
            className="rounded-md border border-zinc-300 px-5 py-2.5 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            {t("auth.registerLink")}
          </Link>
        </div>
      </main>
    </div>
  );
}
