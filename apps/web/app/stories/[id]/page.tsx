"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { SWIPE_THRESHOLD_PX } from "@/lib/constants";
import { startPolling } from "@/lib/polling";
import {
  storyCreateFailure,
  storyCreateMessage,
  storyFailureMessageKey,
  storyGenerationStageMessageKey,
  storyRecoveryMessage,
} from "@/lib/story-create-errors";
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
  const [recoveryAction, setRecoveryAction] = useState<"retry" | "restart" | null>(null);
  const [recoveryError, setRecoveryError] = useState("");
  const [pollingGeneration, setPollingGeneration] = useState(0);

  useEffect(() => {
    return startPolling({
      load: () => api.getStory(id),
      shouldContinue: (loaded) => loaded.status === "generating",
      onValue: (loaded) => {
        setStory(loaded);
        setDraft(loaded.event_text ?? "");
        setLoadError("");
        setRegenerateError("");
        setRegenerating(false);
      },
      onError: () => setLoadError(t("common.loadFailed")),
    });
  }, [id, pollingGeneration, t]);

  async function handleRetry() {
    if (!story || recoveryAction) return;
    setRecoveryError("");
    setRecoveryAction("retry");
    try {
      const updated = await api.retryFailedStory(id);
      setStory((current) => current ? { ...current, ...updated } : current);
      setPollingGeneration((value) => value + 1);
    } catch (error) {
      setRecoveryError(t(storyRecoveryMessage(error).key));
      setRecoveryAction(null);
    }
  }

  async function handleRestart(e: React.FormEvent) {
    e.preventDefault();
    const eventText = draft.trim();
    if (!story || !eventText || recoveryAction) return;
    setRecoveryError("");
    setRecoveryAction("restart");
    try {
      const updated = await api.restartFailedStory(id, eventText);
      setStory((current) => current ? { ...current, ...updated } : current);
      setPollingGeneration((value) => value + 1);
    } catch (error) {
      setRecoveryError(t(storyRecoveryMessage(error).key));
      setRecoveryAction(null);
    }
  }

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
      const message = storyCreateMessage(failure, {
        surface: "regeneration",
      });
      setRegenerateError(t(message.key, message.params));
      setRegenerating(false);
    }
  }

  if (loadError) {
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 space-y-4 px-4 py-8 sm:px-6 lg:px-8">
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
      </main>
    );
  }

  if (!story) return <main className="p-8">{t("common.loading")}</main>;

  if (story.status === "generation_failed") {
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 space-y-5 px-4 py-8 sm:px-6 lg:px-8">
        <BackLink childId={story.child_id} />
        <h1 className="text-xl font-semibold">{t("reader.generationFailedTitle")}</h1>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">
          {t(storyFailureMessageKey(story.failure_reason))}
        </p>
        {story.recovery_allowed ? (
          <>
            <button
              type="button"
              onClick={handleRetry}
              disabled={recoveryAction !== null}
              aria-busy={recoveryAction === "retry"}
              className="w-full rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {recoveryAction === "retry" ? t("reader.retryingGeneration") : t("reader.retryGeneration")}
            </button>
            <form onSubmit={handleRestart} className="space-y-3 rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <p className="text-sm text-zinc-500 dark:text-zinc-400">{t("reader.editAndRestart")}</p>
              <label htmlFor="restart-event" className="block text-sm font-medium">{t("reader.eventLabel")}</label>
              <textarea
                id="restart-event"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={4}
                className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
              />
              <button
                type="submit"
                disabled={recoveryAction !== null || draft.trim().length === 0}
                aria-busy={recoveryAction === "restart"}
                className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm font-medium disabled:opacity-50 dark:border-zinc-600"
              >
                {recoveryAction === "restart" ? t("reader.restartGeneration") : t("reader.editAndRestart")}
              </button>
            </form>
            {recoveryError && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{recoveryError}</p>}
          </>
        ) : (
          <>
            <p className="text-sm text-zinc-500 dark:text-zinc-400">{t("generationErrors.attemptsExhausted")}</p>
            <Link href={`/children/${story.child_id}`} className="text-sm text-indigo-600 dark:text-indigo-400">
              {t("reader.startNewStory")}
            </Link>
          </>
        )}
      </main>
    );
  }

  if (story.status === "generating") {
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 space-y-4 px-4 py-8 sm:px-6 lg:px-8">
        <BackLink childId={story.child_id} />
        <h1 className="text-xl font-semibold">{t("reader.generatingTitle")}</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">{t(storyGenerationStageMessageKey(story.generation_stage))}</p>
      </main>
    );
  }

  if (story.status === "rejected") {
    const canRegenerate = story.safety_reason !== null && story.event_text !== null;
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 space-y-5 px-4 py-8 sm:px-6 lg:px-8">
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
            className="space-y-3 rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
          >
            <p className="text-sm text-zinc-500 dark:text-zinc-400">{t("reader.editAndRegenerate")}</p>
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
              <p role="alert" className="text-sm text-red-600 dark:text-red-400">{regenerateError}</p>
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
      <main className="mx-auto w-full max-w-6xl flex-1 space-y-6 px-4 py-8 sm:px-6 lg:px-8">
        <header className="space-y-4">
          <BackLink childId={story.child_id} />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-medium text-indigo-600 dark:text-indigo-400">{t("reader.reviewLabel")}</p>
              <h1 className="mt-1 break-words text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
                {t("reader.previewTitle", { title: story.title })}
              </h1>
            </div>
            <p className="max-w-sm text-sm leading-6 text-zinc-500 sm:text-right dark:text-zinc-400">
              {t("reader.costNote", { cost: Number(story.cost_usd).toFixed(3) })}
            </p>
          </div>
        </header>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {story.pages.map((p) => (
            <article
              key={p.page_number}
              className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
            >
              {p.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={p.image_url}
                  alt={t("reader.pageIllustrationAlt", { n: p.page_number })}
                  className="aspect-[4/3] w-full object-cover"
                />
              )}
              <div className="space-y-2 p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                  {t("reader.pageNumber", { n: p.page_number })}
                </p>
                <p className="text-sm leading-6">{p.text}</p>
              </div>
            </article>
          ))}
        </div>
        <div className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-zinc-50 p-4 sm:flex-row sm:items-center sm:justify-end dark:border-zinc-800 dark:bg-zinc-900">
          <p className="text-sm text-zinc-600 sm:mr-auto dark:text-zinc-400">{t("reader.reviewPrompt")}</p>
          <button
            onClick={() => handleApprove(true)}
            disabled={reviewing}
            aria-busy={reviewing}
            className="rounded-lg bg-green-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {t("reader.approve")}
          </button>
          <button
            onClick={() => handleApprove(false)}
            disabled={reviewing}
            aria-busy={reviewing}
            className="rounded-lg border border-zinc-300 bg-white px-4 py-2.5 text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-950 dark:hover:bg-zinc-800"
          >
            {t("reader.reject")}
          </button>
        </div>
        {actionError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">{actionError}</p>
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
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col space-y-4 px-4 py-6 sm:space-y-6 sm:px-6 lg:px-8">
      <BackLink childId={story.child_id} />
      <h1 className="text-lg font-semibold sm:text-xl">{story.title}</h1>
      <div
        key={page}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
        className={`grid flex-1 items-center gap-6 rounded-xl border border-zinc-200 bg-white p-4 shadow-sm sm:p-6 dark:border-zinc-800 dark:bg-zinc-900 ${current.image_url ? "md:grid-cols-2" : ""}`}
      >
        {current.image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={current.image_url}
            alt={t("reader.pageIllustrationAlt", { n: current.page_number })}
            className="w-full rounded-lg"
          />
        )}
        <div className="min-w-0">
          <p className="text-base leading-relaxed sm:text-lg">{current.text}</p>
          {current.audio_url ? (
            <audio ref={audioRef} controls src={current.audio_url} className="mt-4 w-full" />
          ) : null}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          onClick={goPrev}
          disabled={page === 0}
          aria-label={t("reader.prev")}
          className="min-w-24 rounded-lg border border-zinc-300 px-4 py-2.5 text-sm disabled:opacity-40 dark:border-zinc-600"
        >
          {t("reader.prev")}
        </button>
        <span className="text-sm text-zinc-500 dark:text-zinc-400">
          {page + 1} / {story.pages.length}
        </span>
        <button
          onClick={goNext}
          disabled={page === lastPage}
          aria-label={t("reader.next")}
          className="min-w-24 rounded-lg border border-zinc-300 px-4 py-2.5 text-sm disabled:opacity-40 dark:border-zinc-600"
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
    <Link href={`/children/${childId}`} className="text-sm text-indigo-600 dark:text-indigo-400">
      {t("common.backToChildren")}
    </Link>
  );
}
