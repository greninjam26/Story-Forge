"use client";

import Script from "next/script";
import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { startAuthSession } from "@/lib/auth-session";
import { useLocale, useT } from "@/lib/i18n";

type CredentialResponse = { credential: string };

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(options: {
            client_id: string;
            callback: (response: CredentialResponse) => void;
          }): void;
          renderButton(
            element: HTMLElement,
            options: Record<string, string | number>,
          ): void;
        };
      };
    };
  }
}

export function GoogleSignIn({ locale }: { locale: "en" | "fr" }) {
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const t = useT();
  const { setLocale } = useLocale();
  const router = useRouter();
  const buttonRef = useRef<HTMLDivElement>(null);
  const [pendingCredential, setPendingCredential] = useState<string | null>(null);
  const [linkPassword, setLinkPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authenticate = useCallback(
    async (credential: string, password?: string) => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.googleAuth(credential, locale, password);
        startAuthSession(response, setLocale);
        router.push("/children");
      } catch (caught) {
        if (
          caught instanceof ApiError &&
          caught.code === "google_link_password_required"
        ) {
          setPendingCredential(credential);
        } else if (
          caught instanceof ApiError &&
          caught.code === "google_account_conflict"
        ) {
          setError(t("auth.googleConflict"));
        } else if (caught instanceof ApiError && caught.status === 503) {
          setError(t("auth.googleUnavailable"));
        } else if (password && caught instanceof ApiError && caught.status === 401) {
          setError(t("auth.invalidCredentials"));
        } else {
          setError(t("auth.googleFailed"));
        }
      } finally {
        setLoading(false);
      }
    },
    [locale, router, setLocale, t],
  );

  const renderButton = useCallback(() => {
    if (!clientId || !buttonRef.current || !window.google) return;
    buttonRef.current.replaceChildren();
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: (response) => void authenticate(response.credential),
    });
    window.google.accounts.id.renderButton(buttonRef.current, {
      type: "standard",
      theme: "outline",
      size: "large",
      text: "continue_with",
      shape: "rectangular",
      width: 320,
      locale,
    });
  }, [authenticate, clientId, locale]);

  if (!clientId) return null;

  return (
    <div className="mt-5">
      <div className="mb-4 flex items-center gap-3 text-sm text-zinc-500">
        <span className="h-px flex-1 bg-zinc-300 dark:bg-zinc-700" />
        <span>{t("auth.or")}</span>
        <span className="h-px flex-1 bg-zinc-300 dark:bg-zinc-700" />
      </div>
      {!pendingCredential && (
        <div
          ref={buttonRef}
          className={loading ? "pointer-events-none opacity-50" : "flex justify-center"}
          aria-busy={loading}
        />
      )}
      {pendingCredential && (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void authenticate(pendingCredential, linkPassword);
          }}
        >
          <p className="text-sm text-zinc-700 dark:text-zinc-300">
            {t("auth.googleLinkPrompt")}
          </p>
          <label>
            <span className="sr-only">{t("auth.googleLinkPassword")}</span>
            <input
              type="password"
              value={linkPassword}
              onChange={(event) => setLinkPassword(event.target.value)}
              placeholder={t("auth.googleLinkPassword")}
              required
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            />
          </label>
          <button
            type="submit"
            disabled={loading}
            className="rounded-md border border-indigo-600 px-4 py-2 text-sm font-medium text-indigo-600 disabled:opacity-50"
          >
            {loading ? t("auth.googleLinking") : t("auth.googleLinkSubmit")}
          </button>
        </form>
      )}
      {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onReady={renderButton}
        onError={() => setError(t("auth.googleUnavailable"))}
      />
    </div>
  );
}
