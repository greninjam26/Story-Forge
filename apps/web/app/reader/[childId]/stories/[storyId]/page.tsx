"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { use } from "react";
import { readerApi } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { ReaderStory } from "@/lib/types";

const SWIPE_THRESHOLD_PX = 40;

function StoryReader({
  childId,
  storyId,
}: {
  childId: string;
  storyId: string;
}) {
  const t = useT();
  const [story, setStory] = useState<ReaderStory | null>(null);
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    readerApi
      .getStory(storyId)
      .then(setStory)
      .catch(() => setError(t("childReader.notFound")));
  }, [storyId, t]);

  if (error) {
    return (
      <main className="flex flex-1 items-center justify-center p-8">
        <div className="space-y-4 text-center">
          <p role="alert" className="text-sm text-red-600">{error}</p>
          <Link
            href={`/reader/${childId}`}
            className="text-sm text-indigo-600 hover:underline"
          >
            {t("common.back")}
          </Link>
        </div>
      </main>
    );
  }

  if (!story) {
    return (
      <main className="flex flex-1 items-center justify-center p-8" aria-live="polite">
        <p className="text-zinc-500">{t("childReader.loading")}</p>
      </main>
    );
  }

  return (
    <Reader story={story} childId={childId} page={page} setPage={setPage} />
  );
}

function Reader({
  story,
  childId,
  page,
  setPage,
}: {
  story: ReaderStory;
  childId: string;
  page: number;
  setPage: React.Dispatch<React.SetStateAction<number>>;
}) {
  const t = useT();
  const current = story.pages[page];
  const lastPage = story.pages.length - 1;
  const audioRef = useRef<HTMLAudioElement>(null);
  const touchStartX = useRef<number | null>(null);

  const goPrev = useCallback(() => setPage((p) => Math.max(0, p - 1)), [setPage]);
  const goNext = useCallback(
    () => setPage((p) => Math.min(lastPage, p + 1)),
    [setPage, lastPage],
  );

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.load();
    audio.play().catch(() => {});
    return () => audio.pause();
  }, [page, current?.audio_url]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft") goPrev();
      if (e.key === "ArrowRight") goNext();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goPrev, goNext]);

  function onTouchStart(e: React.TouchEvent) {
    touchStartX.current = e.touches[0].clientX;
  }
  function onTouchEnd(e: React.TouchEvent) {
    if (touchStartX.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    touchStartX.current = null;
    if (dx > SWIPE_THRESHOLD_PX) goPrev();
    if (dx < -SWIPE_THRESHOLD_PX) goNext();
  }

  return (
    <main className="mx-auto flex w-full max-w-lg flex-1 flex-col p-4 sm:p-6">
      <Link
        href={`/reader/${childId}`}
        className="mb-4 self-start text-sm text-indigo-600"
      >
        {t("common.back")}
      </Link>

      <div
        key={page}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
        className="flex flex-1 flex-col items-center"
      >
        {current.image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={current.image_url}
            alt={story.title}
            className="mb-4 w-full rounded-xl"
          />
        )}
        <p className="mb-4 text-center text-lg leading-relaxed sm:text-xl">
          {current.text}
        </p>
        {current.audio_url ? (
          <audio
            ref={audioRef}
            controls
            src={current.audio_url}
            className="mb-4 w-full max-w-sm"
          />
        ) : null}
      </div>

      <div className="mt-auto flex items-center justify-between gap-3 pt-4">
        <button
          onClick={goPrev}
          disabled={page === 0}
          aria-label={t("childReader.prev")}
          className="min-w-28 rounded-full border border-zinc-300 px-6 py-3 text-sm font-medium disabled:opacity-30 dark:border-zinc-600"
        >
          {t("childReader.prev")}
        </button>
        <span className="text-sm text-zinc-500">
          {t("childReader.pageOf", { current: page + 1, total: story.pages.length })}
        </span>
        <button
          onClick={goNext}
          disabled={page === lastPage}
          aria-label={t("childReader.next")}
          className="min-w-28 rounded-full border border-zinc-300 px-6 py-3 text-sm font-medium disabled:opacity-30 dark:border-zinc-600"
        >
          {t("childReader.next")}
        </button>
      </div>
    </main>
  );
}

function ParamsWrapper({
  params,
}: {
  params: Promise<{ childId: string; storyId: string }>;
}) {
  const { childId, storyId } = use(params);
  return <StoryReader childId={childId} storyId={storyId} />;
}

export default function ChildStoryReader({
  params,
}: {
  params: Promise<{ childId: string; storyId: string }>;
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
