"use client";

import { Suspense, useCallback, useEffect, useRef, useState, use } from "react";
import Link from "next/link";
import { readerApi } from "@/lib/api";
import { SWIPE_THRESHOLD_PX } from "@/lib/constants";
import { useT } from "@/lib/i18n";
import type { ReaderStory } from "@/lib/types";

function StoryReader({
  readerToken,
  storyId,
}: {
  readerToken: string;
  storyId: string;
}) {
  const t = useT();
  const [story, setStory] = useState<ReaderStory | null>(null);
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    readerApi
      .getStory(readerToken, storyId)
      .then(setStory)
      .catch(() => setError(t("childReader.notFound")));
  }, [readerToken, storyId, t]);

  if (error) {
    return (
      <main className="flex flex-1 items-center justify-center p-8">
        <div className="space-y-4 text-center">
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>
          <Link
            href={`/reader/${readerToken}`}
            className="text-sm text-indigo-600 hover:underline dark:text-indigo-400"
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
        <p className="text-zinc-500 dark:text-zinc-400">{t("childReader.loading")}</p>
      </main>
    );
  }

  return (
    <Reader story={story} readerToken={readerToken} page={page} setPage={setPage} />
  );
}

function Reader({
  story,
  readerToken,
  page,
  setPage,
}: {
  story: ReaderStory;
  readerToken: string;
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
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-4 py-6 sm:px-6 lg:px-8">
      <Link
        href={`/reader/${readerToken}`}
        className="mb-4 self-start text-sm text-indigo-600 dark:text-indigo-400"
      >
        {t("common.back")}
      </Link>

      <div
        key={page}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
        className={`grid flex-1 items-center gap-6 rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm sm:p-6 dark:border-zinc-800 dark:bg-zinc-900 ${current.image_url ? "md:grid-cols-2" : ""}`}
      >
        {current.image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={current.image_url}
            alt={story.title}
            className="w-full rounded-xl"
          />
        )}
        <div className="min-w-0 text-center md:text-left">
          <p className="text-lg leading-relaxed sm:text-xl">
            {current.text}
          </p>
          {current.audio_url ? (
            <audio
              ref={audioRef}
              controls
              src={current.audio_url}
              className="mt-5 w-full"
            />
          ) : null}
        </div>
      </div>

      <div className="mt-auto grid grid-cols-[1fr_auto_1fr] items-center gap-2 pt-4 sm:gap-4">
        <button
          onClick={goPrev}
          disabled={page === 0}
          aria-label={t("childReader.prev")}
          className="min-w-0 justify-self-start rounded-full border border-zinc-300 px-4 py-3 text-sm font-medium disabled:opacity-30 sm:px-6 dark:border-zinc-600"
        >
          <span aria-hidden="true" className="sm:hidden">←</span>
          <span className="hidden sm:inline">{t("childReader.prev")}</span>
        </button>
        <span className="text-center text-xs text-zinc-500 sm:text-sm dark:text-zinc-400">
          {t("childReader.pageOf", { current: page + 1, total: story.pages.length })}
        </span>
        <button
          onClick={goNext}
          disabled={page === lastPage}
          aria-label={t("childReader.next")}
          className="min-w-0 justify-self-end rounded-full border border-zinc-300 px-4 py-3 text-sm font-medium disabled:opacity-30 sm:px-6 dark:border-zinc-600"
        >
          <span aria-hidden="true" className="sm:hidden">→</span>
          <span className="hidden sm:inline">{t("childReader.next")}</span>
        </button>
      </div>
    </main>
  );
}

function ParamsWrapper({
  params,
}: {
  params: Promise<{ readerToken: string; storyId: string }>;
}) {
  const { readerToken, storyId } = use(params);
  return <StoryReader readerToken={readerToken} storyId={storyId} />;
}

export default function ChildStoryReader({
  params,
}: {
  params: Promise<{ readerToken: string; storyId: string }>;
}) {
  const t = useT();
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center p-8" aria-live="polite">
          <p className="text-zinc-500 dark:text-zinc-400">{t("childReader.loading")}</p>
        </main>
      }
    >
      <ParamsWrapper params={params} />
    </Suspense>
  );
}
