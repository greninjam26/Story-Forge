"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import { storyCreateFailure, storyCreateMessageKey } from "@/lib/story-create-errors.mjs";
import { useT } from "@/lib/i18n";
import type { Child, Parent, StoryOut, StoryStatus } from "@/lib/types";

export default function ChildDashboard({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useT();
  const router = useRouter();
  const [child, setChild] = useState<Child | null>(null);
  const [parent, setParent] = useState<Parent | null>(null);
  const [stories, setStories] = useState<StoryOut[]>([]);
  const [eventText, setEventText] = useState("");
  const [error, setError] = useState("");
  const [limitHit, setLimitHit] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((p) => {
        if (cancelled) return;
        setParent(p);
        return api.getChild(p.id, id);
      })
      .then((c) => {
        if (cancelled || !c) return;
        setChild(c);
        return api.listStories(c.id);
      })
      .then((list) => {
        if (!cancelled && list) setStories(list);
      })
      .catch((err) => {
        if (!cancelled) {
          if (err instanceof ApiError && err.status === 401) router.replace("/");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id, router]);

  const remaining =
    parent && !parent.is_subscribed
      ? Math.max(0, 3 - parent.free_stories_used)
      : null;

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
      api.me().then(setParent).catch(() => {});
    } catch (err) {
      const failure = storyCreateFailure(err);
      if (failure === "quota") {
        setLimitHit(true);
      } else {
        setError(t(storyCreateMessageKey(failure, "dashboard")));
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleUpgrade() {
    try {
      const res = await api.checkout();
      if (res.checkout_url) {
        window.location.href = res.checkout_url;
      } else {
        setLimitHit(false);
        api.me().then(setParent).catch(() => {});
      }
    } catch {
      setError(t("children.portalUnavailable"));
    }
  }

  if (!child) return <main className="p-8">{t("common.loading")}</main>;

  return (
    <main className="mx-auto w-full max-w-lg flex-1 space-y-8 p-8">
      <Link href="/children" className="text-sm text-indigo-600">
        {t("common.back")}
      </Link>
      <h1 className="text-xl font-semibold">
        {t("child.tonightTitle", { name: child.name })}
      </h1>

      <form
        onSubmit={handleGenerate}
        className="space-y-3 rounded-md border border-zinc-200 p-4 dark:border-zinc-700"
      >
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium">{t("child.whatHappened")}</label>
          {remaining !== null && (
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs ${
                remaining === 0
                  ? "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
                  : "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300"
              }`}
            >
              {t("child.freeRemaining", { n: remaining })}
            </span>
          )}
        </div>
        <textarea
          required
          value={eventText}
          onChange={(e) => setEventText(e.target.value)}
          placeholder={t("child.eventPlaceholder")}
          className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
          rows={3}
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        {limitHit || remaining === 0 ? (
          <div className="space-y-2 rounded-md bg-amber-50 p-3 dark:bg-amber-950">
            <p className="text-sm text-amber-800 dark:text-amber-300">
              {t("child.limitReached", { name: child.name })}
            </p>
            <button
              type="button"
              onClick={handleUpgrade}
              className="w-full rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-white"
            >
              {t("child.upgradeContinue")}
            </button>
          </div>
        ) : (
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {loading ? t("child.generating") : t("child.generate")}
          </button>
        )}
      </form>

      <div className="space-y-2">
        <h2 className="text-sm font-medium text-zinc-500">{t("child.pastBooks")}</h2>
        <ul className="space-y-2">
          {stories.map((story) => (
            <li key={story.id}>
              <Link
                href={`/stories/${story.id}`}
                className="block rounded-md border border-zinc-200 px-4 py-3 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                <span className="font-medium">{story.title || t("child.untitled")}</span>
                <span className="ml-2 text-xs text-zinc-500">
                  {t(statusKey(story.status))}
                </span>
              </Link>
            </li>
          ))}
          {stories.length === 0 && (
            <p className="text-sm text-zinc-500">{t("child.noBooks")}</p>
          )}
        </ul>
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
