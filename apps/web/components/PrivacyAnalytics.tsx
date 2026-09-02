"use client";

import { Analytics } from "@vercel/analytics/next";
import { redactAnalyticsEvent } from "@/lib/analytics-privacy";

export function PrivacyAnalytics() {
  if (process.env.NEXT_PUBLIC_VERCEL_ANALYTICS_ENABLED === "false") {
    return null;
  }

  return <Analytics beforeSend={redactAnalyticsEvent} />;
}
