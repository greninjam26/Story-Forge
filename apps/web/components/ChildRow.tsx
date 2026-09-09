"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { Child } from "@/lib/types";
import { ChildProfileEditor } from "@/components/ChildProfileEditor";

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
  const [error, setError] = useState("");

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
      <li className="md:col-span-2">
        <ChildProfileEditor
          child={child}
          parentId={parentId}
          onSaved={onUpdated}
          onCancel={() => setEditing(false)}
        />
      </li>
    );
  }

  return (
    <li className="flex min-w-0 flex-col rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">{child.name}</h3>
          <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            {t("children.yearsOld", { age: child.age })}
          </span>
        </div>
        <p className="mt-2 break-words text-sm leading-6 text-zinc-600 dark:text-zinc-400">
          {child.interests || t("children.noInterests")}
        </p>
        <p className="mt-1 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          {child.language === "en" ? t("children.langEn") : t("children.langFr")}
        </p>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-2 text-sm">
        <Link
          href={`/children/${child.id}`}
          className="rounded-lg bg-indigo-600 px-3.5 py-2 font-medium text-white hover:bg-indigo-700"
        >
          {t("children.openProfile")}
        </Link>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="rounded-lg border border-zinc-300 px-3.5 py-2 font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          {t("children.editProfile")}
        </button>
        <button
          type="button"
          onClick={handleDelete}
          className="ml-auto px-2 py-2 text-red-600 hover:underline dark:text-red-400"
        >
          {t("children.delete")}
        </button>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </li>
  );
}
