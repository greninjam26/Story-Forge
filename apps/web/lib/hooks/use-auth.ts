"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Parent } from "@/lib/types";

/**
 * Require authentication and return mutable parent profile state.
 * Redirects to `redirectTo` on any API failure.
 */
export function useRequireAuth(redirectTo = "/") {
  const router = useRouter();
  const [parent, setParent] = useState<Parent | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((p) => {
        if (!cancelled) setParent(p);
      })
      .catch(() => {
        if (!cancelled) router.replace(redirectTo);
      });
    return () => {
      cancelled = true;
    };
  }, [router, redirectTo]);

  return [parent, setParent] as const;
}
