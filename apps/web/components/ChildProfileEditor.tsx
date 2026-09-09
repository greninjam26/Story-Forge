"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { Child } from "@/lib/types";
import { ReferencePhotoInput } from "@/components/ReferencePhotoInput";

export function ChildProfileEditor({
  child,
  parentId,
  onSaved,
  onCancel,
}: {
  child: Child;
  parentId: string;
  onSaved: (child: Child) => void;
  onCancel: () => void;
}) {
  const t = useT();
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
      onSaved(updated);
      if (photo) {
        try {
          await api.uploadReferencePhoto(parentId, child.id, photo);
        } catch {
          setError(t("children.photoUploadAfterSave"));
          return;
        }
      }
      onCancel();
    } catch {
      setError(t("children.saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSave}
      className="space-y-4 rounded-xl border border-indigo-200 bg-indigo-50/50 p-4 dark:border-indigo-900 dark:bg-indigo-950/30"
    >
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_7rem]">
        <label className="space-y-1.5 text-sm font-medium">
          <span>{t("children.namePlaceholder")}</span>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-normal dark:border-zinc-600 dark:bg-zinc-900"
          />
        </label>
        <label className="space-y-1.5 text-sm font-medium">
          <span>{t("children.agePlaceholder")}</span>
          <input
            required
            type="number"
            min={1}
            max={12}
            value={age}
            onChange={(e) => setAge(Number(e.target.value))}
            className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-normal dark:border-zinc-600 dark:bg-zinc-900"
          />
        </label>
      </div>
      <label className="block space-y-1.5 text-sm font-medium">
        <span>{t("children.interestsLabel")}</span>
        <input
          value={interests}
          onChange={(e) => setInterests(e.target.value)}
          className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-normal dark:border-zinc-600 dark:bg-zinc-900"
          placeholder={t("children.interestsPlaceholder")}
        />
      </label>
      <label className="block space-y-1.5 text-sm font-medium">
        <span>{t("children.storyLanguageLabel")}</span>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as "en" | "fr")}
          className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-normal dark:border-zinc-600 dark:bg-zinc-900"
        >
          <option value="en">{t("children.langEn")}</option>
          <option value="fr">{t("children.langFr")}</option>
        </select>
      </label>
      <ReferencePhotoInput file={photo} onFileChange={setPhoto} />
      {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={saving}
          aria-busy={saving}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? t("common.loading") : t("children.saveChanges")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900 dark:hover:bg-zinc-800"
        >
          {t("children.cancel")}
        </button>
      </div>
    </form>
  );
}
