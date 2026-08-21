"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { SWIPE_THRESHOLD_PX } from "@/lib/constants";
import { storyCreateFailure, storyCreateMessageKey } from "@/lib/story-create-errors";
import { useT } from "@/lib/i18n";
import type { StoryDetail } from "@/lib/types";

export default function StoryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useT();
  const router = useRouter();
  const [story, setStory] = useState<StoryDetail | null>(null);
  const [page, setPage] = useState(0);
  const [draft, setDraft] = useState("");
  const [regenerating, setRegenerating] = useState(false);
  const [regenerateError, setRegenerateError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [reviewing, setReviewing] = useState(false);

  useEffect(() => {
    api.getStory(id).then((loaded) => {
      setStory(loaded);
      setDraft(loaded.event_text ?? "");
      setRegenerateError("");
      setRegenerating(false);
    }).catch(() => setLoadError(t("common.loadFailed")));
  }, [id, t]);

  async function handleApprove(approve: boolean) {
    if (reviewing) return;
    setActionError("");
    setReviewing(true);
    try {
      const updated = await api.approveStory(id, approve);
      setStory((current) => current ? { ...current, ...updated } : current);
    } catch {
      setActionError(t("reader.reviewFailed"));
    } finally {
      setReviewing(false);
    }
  }

  async function handleRegenerate(e: React.FormEvent) {
    e.preventDefault();
    const eventText = draft.trim();
    if (!story || !eventText || regenerating) return;
    setRegenerateError("");
    setRegenerating(true);
    try {
      const created = await api.createStory(story.child_id, eventText);
      router.push(`/stories/${created.id}`);
    } catch (err) {
      const failure = storyCreateFailure(err);
      setRegenerateError(t(storyCreateMessageKey(failure, "regeneration")));
      setRegenerating(false);
    }
  }

  if (loadError) {
    return (
      <main className="mx-auto w-full max-w-lg flex-1 space-y-4 p-8">
        <p role="alert" className="text-sm text-red-600">{loadError}</p>
      </main>
    );
  }

  if (!story) return <main className="p-8">{t("common.loading")}</main>;

  if (story.status === "generation_failed") {
    return (
      <main className="mx-auto w-full max-w-lg flex-1 space-y-4 p-8">
        <BackLink childId={story.child_id} />
        <h1 className="text-xl font-semibold">{t("reader.generationFailedTitle")}</h1>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {story.failure_reason || t("generationErrors.generic")}
        </p>
        <p className="text-sm text-zinc-500">{t("reader.retryLater")}</p>
      </main>
    );
  }

  if (story.status === "generating") {
    return (
      <main className="mx-auto w-full max-w-lg flex-1 space-y-4 p-8">
        <BackLink childId={story.child_id} />
        <h1 className="text-xl font-semibold">{t("reader.generatingTitle")}</h1>
        <p className="text-sm text-zinc-500">{t("reader.generatingBody")}</p>
      </main>
    );
  }

  if (story.status === "rejected") {
    const canRegenerate = story.safety_reason !== null && story.event_text !== null;
    return (
      <main className="mx-auto w-full max-w-lg flex-1 space-y-4 p-8">
        <BackLink childId={story.child_id} />
        <h1 className="text-xl font-semibold">{t("reader.rejectedTitle")}</h1>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {story.safety_reason
            ? t("reader.rejectedBody")
            : t("reader.parentRejected")}
        </p>
        {canRegenerate && (
          <form
            onSubmit={handleRegenerate}
            className="space-y-3 rounded-md border border-zinc-200 p-4 dark:border-zinc-700"
          >
            <p className="text-sm text-zinc-500">{t("reader.editAndRegenerate")}</p>
            <label htmlFor="regenerate-event" className="block text-sm font-medium">
              {t("reader.eventLabel")}
            </label>
            <textarea
              id="regenerate-event"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={4}
              className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
            />
            {regenerateError && (
              <p role="alert" className="text-sm text-red-600">{regenerateError}</p>
            )}
            <button
              type="submit"
              disabled={regenerating || draft.trim().length === 0}
              aria-busy={regenerating}
              className="w-full rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {regenerating ? t("reader.regenerating") : t("reader.regenerate")}
            </button>
          </form>
        )}
      </main>
    );
  }

  if (story.status === "pending_review") {
    return (
      <main className="mx-auto w-full max-w-lg flex-1 space-y-6 p-8">
        <BackLink childId={story.child_id} />
        <h1 className="text-xl font-semibold">
          {t("reader.previewTitle", { title: story.title })}
        </h1>
        <p className="text-sm text-zinc-500">
          {t("reader.costNote", { cost: story.cost_usd.toFixed(3) })}
        </p>
        <div className="space-y-4">
          {story.pages.map((p) => (
            <div
              key={p.page_number}
              className="rounded-md border border-zinc-200 p-4 dark:border-zinc-700"
            >
              {p.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={p.image_url}
                  alt={`page ${p.page_number}`}
                  className="mb-3 w-full rounded"
                />
              )}
              <p className="text-sm">{p.text}</p>
            </div>
          ))}
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => handleApprove(true)}
            disabled={reviewing}
            aria-busy={reviewing}
            className="flex-1 rounded-md bg-green-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {t("reader.approve")}
          </button>
          <button
            onClick={() => handleApprove(false)}
            disabled={reviewing}
            aria-busy={reviewing}
            className="flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium disabled:opacity-50 dark:border-zinc-600"
          >
            {t("reader.reject")}
          </button>
        </div>
        {actionError && (
          <p role="alert" className="text-sm text-red-600">{actionError}</p>
        )}
      </main>
    );
  }

  return <Reader story={story} page={page} setPage={setPage} />;
}

function Reader({
  story,
  page,
  setPage,
}: {
  story: StoryDetail;
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
    <main className="mx-auto flex w-full max-w-lg flex-1 flex-col space-y-4 p-4 sm:space-y-6 sm:p-8">
      <BackLink childId={story.child_id} />
      <h1 className="text-lg font-semibold sm:text-xl">{story.title}</h1>
      <div
        key={page}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
        className="flex-1 rounded-md border border-zinc-200 p-4 dark:border-zinc-700"
      >
        {current.image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={current.image_url}
            alt={`page ${current.page_number}`}
            className="mb-3 w-full rounded"
          />
        )}
        <p className="text-base leading-relaxed sm:text-lg">{current.text}</p>
        {current.audio_url ? (
          <audio ref={audioRef} controls src={current.audio_url} className="mt-3 w-full" />
        ) : null}
      </div>
      <div className="flex items-center justify-between gap-3">
        <button
          onClick={goPrev}
          disabled={page === 0}
          aria-label={t("reader.prev")}
          className="min-w-24 rounded-md border border-zinc-300 px-4 py-2.5 text-sm disabled:opacity-40 dark:border-zinc-600"
        >
          {t("reader.prev")}
        </button>
        <span className="text-sm text-zinc-500">
          {page + 1} / {story.pages.length}
        </span>
        <button
          onClick={goNext}
          disabled={page === lastPage}
          aria-label={t("reader.next")}
          className="min-w-24 rounded-md border border-zinc-300 px-4 py-2.5 text-sm disabled:opacity-40 dark:border-zinc-600"
        >
          {t("reader.next")}
        </button>
      </div>
    </main>
  );
}

function BackLink({ childId }: { childId: string }) {
  const t = useT();
  return (
    <Link href={`/children/${childId}`} className="text-sm text-indigo-600">
      {t("common.backToChildren")}
    </Link>
  );
}
