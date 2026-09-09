"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import { storyCreateFailure, storyCreateMessage } from "@/lib/story-create-errors";
import { startPolling } from "@/lib/polling";
import { useT } from "@/lib/i18n";
import { useRequireAuth } from "@/lib/hooks/use-auth";
import { useBilling } from "@/lib/hooks/use-billing";
import type { Child, StoryOut, StoryStatus } from "@/lib/types";
import { ChildProfileEditor } from "@/components/ChildProfileEditor";

export default function ChildDashboard({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useT();
  const router = useRouter();
  const [parent, setParent] = useRequireAuth("/");
  const { checkout } = useBilling(setParent, {
    notConfigured: t("billing.notConfigured"),
    portalUnavailable: t("billing.portalUnavailable"),
  });
  const [child, setChild] = useState<Child | null>(null);
  const [stories, setStories] = useState<StoryOut[]>([]);
  const [eventText, setEventText] = useState("");
  const [error, setError] = useState("");
  const [limitHit, setLimitHit] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editingProfile, setEditingProfile] = useState(false);
  const hasGeneratingStory = stories.some(
    (story) => story.status === "generating",
  );

  useEffect(() => {
    if (!parent) return;
    let cancelled = false;
    api
      .getChild(parent.id, id)
      .then((c) => {
        if (cancelled || !c) return;
        setChild(c);
        return api.listStories(c.id);
      })
      .then((list) => {
        if (!cancelled && list) setStories(list);
      })
      .catch((err) => {
        if (!cancelled && !(err instanceof ApiError && err.status === 401)) {
          router.replace("/");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [parent, id, router]);

  useEffect(() => {
    if (!child || !hasGeneratingStory) return;
    return startPolling({
      load: () => api.listStories(child.id),
      shouldContinue: (loaded) => loaded.some(
        (story) => story.status === "generating",
      ),
      onValue: setStories,
      onError: () => setError(t("common.loadFailed")),
    });
  }, [child, hasGeneratingStory, t]);

  const remaining =
    parent && !parent.is_subscribed
      ? Math.max(
          0,
          parent.free_stories_limit - parent.free_stories_used,
        )
      : null;

  const readerPath = child ? `/reader/${child.reader_access_token}` : "";

  async function copyReaderLink() {
    await navigator.clipboard.writeText(
      `${window.location.origin}${readerPath}`,
    );
  }

  async function resetReaderLink() {
    if (!parent || !window.confirm(t("child.resetReaderLinkConfirm"))) return;
    setError("");
    try {
      setChild(await api.rotateReaderAccessToken(parent.id, child!.id));
    } catch {
      setError(t("common.loadFailed"));
    }
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLimitHit(false);
    setLoading(true);
    try {
      const story = await api.createStory(child!.id, eventText);
      setStories((prev) => [story, ...prev]);
      if (story.status === "generation_failed") {
        setError(t("generationErrors.generic"));
      } else {
        setEventText("");
      }
      void api.me().then(setParent).catch(() => {});
    } catch (err) {
      const failure = storyCreateFailure(err);
      if (failure === "quota") {
        setLimitHit(true);
      } else {
        const message = storyCreateMessage(failure, {
          surface: "dashboard",
          childName: child!.name,
        });
        setError(t(message.key, message.params));
      }
    } finally {
      setLoading(false);
    }
  }

  if (!child) return <main className="p-8">{t("common.loading")}</main>;

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 space-y-8 px-4 py-8 sm:px-6 lg:px-8">
      <header className="space-y-4">
        <Link href="/children" className="inline-flex text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400">
          {t("common.backToChildren")}
        </Link>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-sm font-medium text-indigo-600 dark:text-indigo-400">{t("child.workspaceLabel")}</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              {t("child.tonightTitle", { name: child.name })}
            </h1>
          </div>
          <button
            type="button"
            onClick={() => setEditingProfile((value) => !value)}
            aria-expanded={editingProfile}
            className="self-start rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:bg-zinc-800"
          >
            {editingProfile ? t("children.cancel") : t("children.editProfile")}
          </button>
        </div>
      </header>

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1.5fr)_minmax(18rem,0.8fr)]">
        <div className="order-2 min-w-0 space-y-8 lg:order-1">
          <form
            onSubmit={handleGenerate}
            className="space-y-4 rounded-xl border border-zinc-200 bg-white p-5 shadow-sm sm:p-6 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <label htmlFor="event-text" className="text-base font-semibold">{t("child.whatHappened")}</label>
              {remaining !== null && (
                <span
                  className={`max-w-full rounded-full px-2.5 py-1 text-xs ${
                    remaining === 0
                      ? "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
                      : "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300"
                  }`}
                >
                  {t("child.freeRemaining", { n: remaining })}
                </span>
              )}
            </div>
            <p className="text-sm leading-6 text-zinc-600 dark:text-zinc-400">{t("child.eventHelp")}</p>
            <textarea
              id="event-text"
              required
              value={eventText}
              onChange={(e) => setEventText(e.target.value)}
              placeholder={t("child.eventPlaceholder")}
              className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-3 text-sm dark:border-zinc-600 dark:bg-zinc-950"
              rows={5}
            />
            {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
            {limitHit || remaining === 0 ? (
              <div className="space-y-3 rounded-lg bg-amber-50 p-4 dark:bg-amber-950">
                <p className="text-sm text-amber-800 dark:text-amber-300">
                  {t("child.limitReached", { name: child.name })}
                </p>
                <button
                  type="button"
                  onClick={() => checkout((msg) => setError(msg))}
                  className="w-full rounded-lg bg-amber-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-amber-600"
                >
                  {t("child.upgradeContinue")}
                </button>
              </div>
            ) : (
              <button
                type="submit"
                disabled={loading}
                aria-busy={loading}
                className="w-full rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {loading ? t("child.generating") : t("child.generate")}
              </button>
            )}
          </form>

          <section aria-labelledby="past-books-heading" className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="past-books-heading" className="text-lg font-semibold">{t("child.pastBooks")}</h2>
              <span className="text-sm text-zinc-500 dark:text-zinc-400">
                {t("child.bookCount", { n: stories.length })}
              </span>
            </div>
            <ul className="grid gap-3 sm:grid-cols-2">
              {stories.map((story) => (
                <li key={story.id}>
                  <Link
                    href={`/stories/${story.id}`}
                    className="block h-full rounded-xl border border-zinc-200 bg-white px-4 py-4 shadow-sm hover:border-indigo-300 hover:bg-indigo-50/30 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-indigo-800 dark:hover:bg-indigo-950/20"
                  >
                    <span className="block font-medium">{story.title || t("child.untitled")}</span>
                    <span className="mt-2 inline-block rounded-full bg-zinc-100 px-2.5 py-1 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                      {t(statusKey(story.status))}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            {stories.length === 0 && (
              <p className="rounded-xl border border-dashed border-zinc-300 px-5 py-8 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
                {t("child.noBooks")}
              </p>
            )}
          </section>
        </div>

        <aside className="order-1 min-w-0 space-y-4 lg:order-2">
          {editingProfile ? (
            <ChildProfileEditor
              child={child}
              parentId={parent?.id ?? ""}
              onSaved={setChild}
              onCancel={() => setEditingProfile(false)}
            />
          ) : (
            <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-base font-semibold">{t("child.profileTitle")}</h2>
                <button
                  type="button"
                  onClick={() => setEditingProfile(true)}
                  className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                >
                  {t("children.edit")}
                </button>
              </div>
              <dl className="mt-4 space-y-3 text-sm">
                <div>
                  <dt className="text-zinc-500 dark:text-zinc-400">{t("children.agePlaceholder")}</dt>
                  <dd className="mt-0.5 font-medium">{t("children.yearsOld", { age: child.age })}</dd>
                </div>
                <div>
                  <dt className="text-zinc-500 dark:text-zinc-400">{t("children.interestsLabel")}</dt>
                  <dd className="mt-0.5 break-words font-medium">{child.interests || t("children.noInterests")}</dd>
                </div>
                <div>
                  <dt className="text-zinc-500 dark:text-zinc-400">{t("children.storyLanguageLabel")}</dt>
                  <dd className="mt-0.5 font-medium">{child.language === "en" ? t("children.langEn") : t("children.langFr")}</dd>
                </div>
              </dl>
            </section>
          )}

          <section className="space-y-3 rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-base font-semibold">{t("child.readerAccessTitle")}</h2>
            <p className="text-sm leading-6 text-zinc-500 dark:text-zinc-400">{t("child.readerAccessDescription")}</p>
            <div className="grid gap-2">
              <Link
                href={readerPath}
                target="_blank"
                rel="noreferrer"
                className="rounded-lg bg-indigo-600 px-3 py-2 text-center text-sm font-medium text-white hover:bg-indigo-700"
              >
                {t("child.openReader")}
              </Link>
              <button
                type="button"
                onClick={() => void copyReaderLink()}
                className="rounded-lg border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-600 dark:hover:bg-zinc-800"
              >
                {t("child.copyReaderLink")}
              </button>
              <button
                type="button"
                onClick={() => void resetReaderLink()}
                className="rounded-lg border border-red-300 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950"
              >
                {t("child.resetReaderLink")}
              </button>
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}

function statusKey(status: StoryStatus): string {
  if (status === "generating") return "child.statusGenerating";
  if (status === "pending_review") return "child.statusPending";
  if (status === "approved") return "child.statusApproved";
  if (status === "generation_failed") return "child.statusGenerationFailed";
  return "child.statusRejected";
}
