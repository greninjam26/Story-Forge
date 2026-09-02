import type { BeforeSendEvent } from "@vercel/analytics/next";

const UUID_PATH_SEGMENT =
  /(^|\/)[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?=\/|$)/gi;

export function redactAnalyticsEvent(
  event: BeforeSendEvent,
): BeforeSendEvent {
  const [urlWithoutMetadata] = event.url.split(/[?#]/, 1);
  return {
    ...event,
    url: urlWithoutMetadata.replace(UUID_PATH_SEGMENT, "$1[id]"),
  };
}
