import { ApiError } from "./story-create-errors";

/** Map account-deletion failures to safe, localized parent-facing copy. */
export function accountDeletionMessageKey(error: unknown): string {
  if (
    error instanceof ApiError &&
    error.code === "subscription_cancellation_failed"
  ) {
    return "children.deleteAccountSubscriptionCancellationFailed";
  }
  return "children.deleteAccountFailed";
}
