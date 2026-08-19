"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError, setToken } from "@/lib/api";
import { useT } from "@/lib/i18n";

export default function RegisterPage() {
  const t = useT();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError(t("auth.passwordMismatch"));
      return;
    }

    setLoading(true);
    try {
      const res = await api.register(email, password);
      setToken(res.access_token);
      router.push("/children");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError(t("auth.emailExists"));
        } else {
          setError(err.message);
        }
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
          {t("auth.registerTitle")}
        </h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <input
            type="email"
            placeholder={t("auth.email")}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
          />
          <input
            type="password"
            placeholder={t("auth.password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
          />
          <input
            type="password"
            placeholder={t("auth.confirmPassword")}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            minLength={8}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
          />
          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? t("auth.registering") : t("auth.submitRegister")}
          </button>
        </form>
        <p className="mt-4 text-center text-sm text-zinc-600 dark:text-zinc-400">
          {t("auth.hasAccount")}{" "}
          <Link href="/auth/login" className="text-indigo-600 hover:underline">
            {t("auth.loginLink")}
          </Link>
        </p>
      </div>
    </div>
  );
}
