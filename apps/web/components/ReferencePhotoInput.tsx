"use client";

import { useEffect, useMemo } from "react";
import { useT } from "@/lib/i18n";

export function ReferencePhotoInput({
  file,
  onFileChange,
}: {
  file: File | null;
  onFileChange: (file: File | null) => void;
}) {
  const t = useT();
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  return (
    <div className="space-y-2 rounded-md border border-zinc-200 p-3 dark:border-zinc-700">
      <div>
        <p className="text-sm font-medium">{t("children.photoLabel")}</p>
        <p className="text-xs text-zinc-500">{t("children.photoHelp")}</p>
      </div>
      {previewUrl && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={previewUrl}
          alt={t("children.photoLabel")}
          className="h-28 w-28 rounded-md object-cover"
        />
      )}
      {file && <p className="text-xs text-indigo-600">{t("children.photoSelected")}</p>}
      <div className="flex flex-wrap gap-2">
        <label className="cursor-pointer rounded-md border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-600">
          {t("children.photoChoose")}
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
          />
        </label>
        {file && (
          <button
            type="button"
            onClick={() => onFileChange(null)}
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-600"
          >
            {t("children.cancel")}
          </button>
        )}
      </div>
    </div>
  );
}
