"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, setToken } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { Child, Parent } from "@/lib/types";
import { ChildRow } from "@/components/ChildRow";
import { ReferencePhotoInput } from "@/components/ReferencePhotoInput";

export default function ChildrenPage() {
  const t = useT();
  const router = useRouter();
  const [parent, setParent] = useState<Parent | null>(null);
  const [children, setChildren] = useState<Child[]>([]);
  const [name, setName] = useState("");
  const [age, setAge] = useState(5);
  const [interests, setInterests] = useState("");
  const [language, setLanguage] = useState<"en" | "fr">("en");
  const [photo, setPhoto] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((p) => {
        if (cancelled) return;
        setParent(p);
        return api.listChildren(p.id);
      })
      .then((list) => {
        if (!cancelled && list) setChildren(list);
      })
      .catch(() => {
        if (!cancelled) router.replace("/");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleAddChild(e: React.FormEvent) {
    e.preventDefault();
    if (!parent) return;
    setError("");
    setSaving(true);
    try {
      const child = await api.createChild(parent.id, name, age, interests, language);
      setChildren((prev) => [...prev, child]);
      if (photo) {
        try {
          await api.uploadReferencePhoto(parent.id, child.id, photo);
        } catch {
          setError(t("children.photoUploadAfterSave"));
        }
      }
      setName("");
      setInterests("");
      setPhoto(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("children.saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function handleUpgrade() {
    try {
      const res = await api.checkout();
      if (res.checkout_url) {
        window.location.href = res.checkout_url;
      } else {
        const refreshed = await api.me();
        setParent(refreshed);
      }
    } catch {
      setError(t("children.portalUnavailable"));
    }
  }

  async function handleManageSubscription() {
    try {
      const res = await api.portal();
      window.location.href = res.portal_url;
    } catch {
      setError(t("children.portalUnavailable"));
    }
  }

  function handleLogout() {
    setToken(null);
    router.replace("/");
  }

  async function handleDeleteAccount() {
    if (!window.confirm(t("children.deleteConfirm1"))) return;
    if (!window.confirm(t("children.deleteConfirm2"))) return;
    try {
      await api.deleteAccount();
      setToken(null);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("children.deleteAccountFailed"));
    }
  }

  return (
    <main className="mx-auto w-full max-w-lg flex-1 space-y-8 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t("children.title")}</h1>
        {parent && !parent.is_subscribed && (
          <button
            onClick={handleUpgrade}
            className="rounded-md bg-amber-500 px-3 py-1.5 text-sm font-medium text-white"
          >
            {t("children.upgrade")}
          </button>
        )}
        {parent?.is_subscribed && (
          <button
            onClick={handleManageSubscription}
            className="rounded-md bg-green-100 px-3 py-1.5 text-sm text-green-700 hover:bg-green-200"
            title={t("children.manageSubscription")}
          >
            {t("children.subscribed")}
          </button>
        )}
      </div>

      <ul className="space-y-2">
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
        {children.length === 0 && (
          <p className="text-sm text-zinc-500">{t("children.empty")}</p>
        )}
      </ul>

      <form
        onSubmit={handleAddChild}
        className="space-y-3 rounded-md border border-zinc-200 p-4 dark:border-zinc-700"
      >
        <h2 className="text-sm font-medium">{t("children.addTitle")}</h2>
        <input
          required
          placeholder={t("children.namePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
        />
        <input
          required
          type="number"
          min={1}
          max={12}
          placeholder={t("children.agePlaceholder")}
          value={age}
          onChange={(e) => setAge(Number(e.target.value))}
          className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
        />
        <input
          placeholder={t("children.interestsPlaceholder")}
          value={interests}
          onChange={(e) => setInterests(e.target.value)}
          className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
        />
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as "en" | "fr")}
          className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
        >
          <option value="en">{t("children.storyLangEn")}</option>
          <option value="fr">{t("children.storyLangFr")}</option>
        </select>
        <ReferencePhotoInput file={photo} onFileChange={setPhoto} />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={saving}
          className="w-full rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? t("common.loading") : t("children.add")}
        </button>
      </form>

      <footer className="flex items-center justify-between border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-700">
        <Link href="/privacy" className="hover:text-indigo-600">
          {t("children.privacy")}
        </Link>
        <div className="flex gap-4">
          <button onClick={handleLogout} className="hover:text-indigo-600">
            {t("children.logout")}
          </button>
          <button onClick={handleDeleteAccount} className="text-red-600 hover:underline">
            {t("children.deleteAccount")}
          </button>
        </div>
      </footer>
    </main>
  );
}
