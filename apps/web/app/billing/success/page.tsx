"use client";

import Link from "next/link";
import { useT } from "@/lib/i18n";

export default function BillingSuccessPage() {
  const t = useT();

  return (
    <div className="flex flex-1 flex-col items-center justify-center bg-zinc-50 px-4 dark:bg-zinc-950">
      <main className="flex max-w-sm flex-col items-center gap-6 text-center">
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
          {t("billing.successTitle")}
        </h1>
        <p className="text-lg text-zinc-600 dark:text-zinc-400">
          {t("billing.successBody")}
        </p>
        <Link
          href="/children"
          className="rounded-md bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700"
        >
          {t("billing.backToApp")}
        </Link>
      </main>
    </div>
  );
}
