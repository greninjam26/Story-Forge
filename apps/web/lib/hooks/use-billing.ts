"use client";

import { api } from "@/lib/api";
import type { Parent } from "@/lib/types";

/**
 * Checkout and billing portal actions.
 * Handles redirecting to Stripe or refreshing parent data on stub responses.
 */
export function useBilling(
  setParent: (p: Parent) => void,
  errorMessages: { notConfigured: string; portalUnavailable: string },
) {
  async function checkout(onError?: (msg: string) => void) {
    try {
      const res = await api.checkout();
      if (res.checkout_url) {
        window.location.href = res.checkout_url;
      } else {
        const refreshed = await api.me();
        setParent(refreshed);
      }
    } catch {
      onError?.(errorMessages.notConfigured);
    }
  }

  async function openPortal(onError?: (msg: string) => void) {
    try {
      const res = await api.portal();
      window.location.href = res.portal_url;
    } catch {
      onError?.(errorMessages.portalUnavailable);
    }
  }

  return { checkout, openPortal };
}
