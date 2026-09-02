"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { startAuthSession } from "@/lib/auth-session";
import { useLocale, useT } from "@/lib/i18n";
import { GoogleSignIn } from "@/components/GoogleSignIn";

export default function LoginPage() {
  const t = useT();
  const { locale, setLocale } = useLocale();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login(email, password);
      startAuthSession(res, setLocale);
      router.push("/children");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError(t("auth.invalidCredentials"));
      } else {
        setError(t("auth.invalidCredentials"));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 px-4 dark:bg-zinc-950">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-center text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
          {t("auth.loginTitle")}
        </h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="block">
            <span className="sr-only">{t("auth.email")}</span>
            <input
              type="email"
              placeholder={t("auth.email")}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            />
          </label>
          <label className="block">
            <span className="sr-only">{t("auth.password")}</span>
            <input
              type="password"
              placeholder={t("auth.password")}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            />
          </label>
          {error && (
            <p role="alert" className="text-sm text-red-600">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading}
            aria-busy={loading}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? t("auth.loggingIn") : t("auth.submitLogin")}
          </button>
        </form>
        <GoogleSignIn locale={locale} />
        <p className="mt-4 text-center text-sm text-zinc-600 dark:text-zinc-400">
          {t("auth.noAccount")}{" "}
          <Link href="/auth/register" className="text-indigo-600 hover:underline">
            {t("auth.registerLink")}
          </Link>
        </p>
      </div>
    </div>
  );
}
