"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, setToken } from "@/lib/api";
import { accountDeletionMessageKey } from "@/lib/account-deletion-errors";
import { useT } from "@/lib/i18n";
import { useRequireAuth } from "@/lib/hooks/use-auth";
import { useAsyncAction } from "@/lib/hooks/use-async-action";
import { useBilling } from "@/lib/hooks/use-billing";
import type { Child } from "@/lib/types";
import { ChildRow } from "@/components/ChildRow";
import { ReferencePhotoInput } from "@/components/ReferencePhotoInput";

export default function ChildrenPage() {
  const t = useT();
  const router = useRouter();
  const [parent, setParent] = useRequireAuth();
  const { error, setError, loading: saving, run } = useAsyncAction();

  const [children, setChildren] = useState<Child[]>([]);
  const [name, setName] = useState("");
  const [age, setAge] = useState(5);
  const [interests, setInterests] = useState("");
  const [language, setLanguage] = useState<"en" | "fr">("en");
  const [photo, setPhoto] = useState<File | null>(null);

  const { checkout, openPortal } = useBilling(setParent, {
    notConfigured: t("billing.notConfigured"),
    portalUnavailable: t("billing.portalUnavailable"),
  });

  useEffect(() => {
    if (parent) {
      api.listChildren(parent.id).then(setChildren).catch(() => setError(t("common.loadFailed")));
    }
  }, [parent, t, setError]);

  async function handleAddChild(e: React.FormEvent) {
    e.preventDefault();
    if (!parent) return;
    await run(async () => {
      const child = await api.createChild(parent.id, name, age, interests, language);
      setChildren((prev) => [...prev, child]);
      if (photo) {
        await api.uploadReferencePhoto(parent.id, child.id, photo).catch(() => {
          setError(t("children.photoUploadAfterSave"));
        });
      }
      setName("");
      setInterests("");
      setPhoto(null);
    });
  }

  function handleLogout() {
    setToken(null);
    router.replace("/");
  }

  async function handleDeleteAccount() {
    if (!window.confirm(t("children.deleteConfirm1"))) return;
    if (!window.confirm(t("children.deleteConfirm2"))) return;
    await run(async () => {
      try {
        await api.deleteAccount();
      } catch (error) {
        throw new Error(t(accountDeletionMessageKey(error)));
      }
      setToken(null);
      router.replace("/");
    });
  }

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 space-y-10 px-4 py-8 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
            {t("children.title")}
          </h1>
          <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-400">
            {t("children.intro")}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href="#add-child"
            className="rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:bg-zinc-800 lg:hidden"
          >
            {t("children.addProfile")}
          </a>
          {parent && !parent.is_subscribed && (
            <button
              onClick={() => checkout((msg) => setError(msg))}
              className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-white hover:bg-amber-600"
            >
              {t("children.upgrade", {
                n: Math.max(
                  0,
                  parent.free_stories_limit - parent.free_stories_used,
                ),
              })}
            </button>
          )}
          {parent?.is_subscribed && (
            <button
              onClick={() => openPortal((msg) => setError(msg))}
              className="rounded-lg bg-green-100 px-4 py-2 text-sm font-medium text-green-800 hover:bg-green-200 dark:bg-green-950 dark:text-green-300 dark:hover:bg-green-900"
              title={t("children.manageSubscription")}
            >
              {t("children.subscribed")}
            </button>
          )}
        </div>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </p>
      )}

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section aria-labelledby="profiles-heading" className="min-w-0 space-y-4">
          <div className="flex items-center justify-between gap-4">
            <h2 id="profiles-heading" className="text-lg font-semibold">
              {t("children.profilesTitle")}
            </h2>
            <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              {t("children.profileCount", { n: children.length })}
            </span>
          </div>
          <ul className="grid gap-4 md:grid-cols-2">
            {children.map((child) => (
              <ChildRow
                key={child.id}
                child={child}
                parentId={parent?.id ?? ""}
                onUpdated={(updated) =>
                  setChildren((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
                }
                onDeleted={(id) => setChildren((prev) => prev.filter((c) => c.id !== id))}
              />
            ))}
          </ul>
          {children.length === 0 && (
            <div className="rounded-xl border border-dashed border-zinc-300 bg-zinc-50 px-5 py-10 text-center dark:border-zinc-700 dark:bg-zinc-900/50">
              <p className="text-sm text-zinc-600 dark:text-zinc-400">{t("children.empty")}</p>
              <a href="#add-child" className="mt-3 inline-block text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                {t("children.addFirstProfile")}
              </a>
            </div>
          )}
        </section>

        <aside id="add-child" className="scroll-mt-4 rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-lg font-semibold">{t("children.addTitle")}</h2>
          <p className="mt-1 text-sm leading-6 text-zinc-600 dark:text-zinc-400">
            {t("children.addDescription")}
          </p>
          <form onSubmit={handleAddChild} className="mt-5 space-y-4">
            <label className="block space-y-1.5 text-sm font-medium">
              <span>{t("children.namePlaceholder")}</span>
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-normal dark:border-zinc-600 dark:bg-zinc-950"
              />
            </label>
            <label className="block space-y-1.5 text-sm font-medium">
              <span>{t("children.agePlaceholder")}</span>
              <input
                required
                type="number"
                min={1}
                max={12}
                value={age}
                onChange={(e) => setAge(Number(e.target.value))}
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-normal dark:border-zinc-600 dark:bg-zinc-950"
              />
            </label>
            <label className="block space-y-1.5 text-sm font-medium">
              <span>{t("children.interestsLabel")}</span>
              <input
                placeholder={t("children.interestsPlaceholder")}
                value={interests}
                onChange={(e) => setInterests(e.target.value)}
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-normal dark:border-zinc-600 dark:bg-zinc-950"
              />
            </label>
            <label className="block space-y-1.5 text-sm font-medium">
              <span>{t("children.storyLanguageLabel")}</span>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value as "en" | "fr")}
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-normal dark:border-zinc-600 dark:bg-zinc-950"
              >
                <option value="en">{t("children.langEn")}</option>
                <option value="fr">{t("children.langFr")}</option>
              </select>
            </label>
            <ReferencePhotoInput file={photo} onFileChange={setPhoto} />
            <button
              type="submit"
              disabled={saving}
              aria-busy={saving}
              className="w-full rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? t("common.loading") : t("children.add")}
            </button>
          </form>
        </aside>
      </div>

      <footer className="flex flex-col gap-4 border-t border-zinc-200 pt-5 text-xs text-zinc-500 sm:flex-row sm:items-center sm:justify-between dark:border-zinc-800 dark:text-zinc-400">
        <nav aria-label={t("navigation.legal")} className="flex flex-wrap gap-x-4 gap-y-2">
          <Link href="/privacy" className="hover:text-indigo-600 dark:hover:text-indigo-400">
            {t("navigation.privacy")}
          </Link>
          <Link href="/terms" className="hover:text-indigo-600 dark:hover:text-indigo-400">
            {t("navigation.terms")}
          </Link>
        </nav>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          <button onClick={handleLogout} className="hover:text-indigo-600 dark:hover:text-indigo-400">
            {t("children.logout")}
          </button>
          <button onClick={handleDeleteAccount} className="text-red-600 hover:underline dark:text-red-400">
            {t("children.deleteAccount")}
          </button>
        </div>
      </footer>
    </main>
  );
}
