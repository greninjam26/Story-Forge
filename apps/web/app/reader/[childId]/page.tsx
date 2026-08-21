"use client";

import { Suspense, useEffect, useState, use } from "react";
import Link from "next/link";
import { readerApi } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { ReaderStory } from "@/lib/types";

function StoryList({ childId }: { childId: string }) {
  const t = useT();
  const [stories, setStories] = useState<ReaderStory[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    readerApi
      .listStories(childId)
      .then(setStories)
      .catch(() => setError(t("childReader.notFound")));
  }, [childId, t]);

  if (error) {
    return (
      <main className="flex flex-1 items-center justify-center p-8">
        <p role="alert" className="text-sm text-red-600">{error}</p>
      </main>
    );
  }

  if (stories === null) {
    return (
      <main className="flex flex-1 items-center justify-center p-8" aria-live="polite">
        <p className="text-zinc-500">{t("childReader.loading")}</p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 p-6 sm:p-8">
      <h1 className="text-center text-2xl font-semibold">
        {t("childReader.title")}
      </h1>

      {stories.length === 0 ? (
        <p className="text-center text-zinc-500">{t("childReader.empty")}</p>
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {stories.map((story) => (
            <li key={story.id}>
              <Link
                href={`/reader/${childId}/stories/${story.id}`}
                className="block overflow-hidden rounded-xl border border-zinc-200 transition-colors hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                {story.pages[0]?.image_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={story.pages[0].image_url}
                    alt={story.title}
                    className="aspect-[4/3] w-full object-cover"
                  />
                )}
                <div className="p-4">
                  <h2 className="font-medium">{story.title}</h2>
                  <p className="mt-1 text-xs text-zinc-500">
                    {story.pages.length === 1
                      ? t("childReader.pageCount", { n: story.pages.length })
                      : t("childReader.pageCountOther", { n: story.pages.length })}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function ParamsWrapper({ params }: { params: Promise<{ childId: string }> }) {
  const { childId } = use(params);
  return <StoryList childId={childId} />;
}

export default function ChildStoryList({
  params,
}: {
  params: Promise<{ childId: string }>;
}) {
  const t = useT();
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center p-8" aria-live="polite">
          <p className="text-zinc-500">{t("childReader.loading")}</p>
        </main>
      }
    >
      <ParamsWrapper params={params} />
    </Suspense>
  );
}
