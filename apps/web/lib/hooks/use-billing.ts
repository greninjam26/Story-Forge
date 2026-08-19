"use client";

import { api } from "@/lib/api";
import type { Parent } from "@/lib/types";

/**
 * Checkout and billing portal actions.
 * Handles redirecting to Stripe or refreshing parent data on stub responses.
 */
export function useBilling(setParent: (p: Parent) => void) {
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
      onError?.("Billing is not configured.");
    }
  }

  async function openPortal(onError?: (msg: string) => void) {
    try {
      const res = await api.portal();
      window.location.href = res.portal_url;
    } catch {
      onError?.("Billing portal is not available.");
    }
  }

  return { checkout, openPortal };
}
