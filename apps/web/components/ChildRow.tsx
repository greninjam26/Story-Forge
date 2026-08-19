"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { Child } from "@/lib/types";
import { ReferencePhotoInput } from "@/components/ReferencePhotoInput";

export function ChildRow({
  child,
  parentId,
  onUpdated,
  onDeleted,
}: {
  child: Child;
  parentId: string;
  onUpdated: (child: Child) => void;
  onDeleted: (id: string) => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(child.name);
  const [age, setAge] = useState(child.age);
  const [interests, setInterests] = useState(child.interests);
  const [language, setLanguage] = useState<"en" | "fr">(child.language);
  const [photo, setPhoto] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const updated = await api.updateChild(parentId, child.id, {
        name,
        age,
        interests,
        language,
      });
      onUpdated(updated);
      if (photo) {
        try {
          await api.uploadReferencePhoto(parentId, child.id, photo);
        } catch {
          setError(t("children.photoUploadAfterSave"));
          return;
        }
      }
      setPhoto(null);
      setEditing(false);
    } catch {
      setError(t("children.saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(t("children.deleteChildConfirm", { name: child.name }))) return;
    try {
      await api.deleteChild(parentId, child.id);
      onDeleted(child.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("children.deleteFailed"));
    }
  }

  if (editing) {
    return (
      <li>
        <form
          onSubmit={handleSave}
          className="space-y-2 rounded-md border border-indigo-200 bg-indigo-50/40 p-4 dark:border-indigo-800 dark:bg-indigo-950/40"
        >
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
            placeholder={t("children.namePlaceholder")}
          />
          <input
            required
            type="number"
            min={1}
            max={12}
            value={age}
            onChange={(e) => setAge(Number(e.target.value))}
            className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
            placeholder={t("children.agePlaceholder")}
          />
          <input
            value={interests}
            onChange={(e) => setInterests(e.target.value)}
            className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
            placeholder={t("children.interestsPlaceholder")}
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
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving}
              className="flex-1 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {saving ? t("common.loading") : t("children.save")}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600"
            >
              {t("children.cancel")}
            </button>
          </div>
        </form>
      </li>
    );
  }

  return (
    <li className="flex items-center justify-between rounded-md border border-zinc-200 px-4 py-3 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800">
      <Link href={`/children/${child.id}`} className="min-w-0 flex-1">
        <span className="font-medium">{child.name}</span>
        <span className="ml-2 text-sm text-zinc-500">
          {t("children.yearsOld", { age: child.age })} ·{" "}
          {child.interests || t("children.noInterests")} ·{" "}
          {child.language === "en" ? "English" : "Français"}
        </span>
      </Link>
      <div className="ml-3 flex flex-none gap-3 text-sm">
        <button onClick={() => setEditing(true)} className="text-indigo-600">
          {t("children.edit")}
        </button>
        <button onClick={handleDelete} className="text-red-600">
          {t("children.delete")}
        </button>
      </div>
      {error && <p className="ml-3 text-sm text-red-600">{error}</p>}
    </li>
  );
}
