// @ts-check

/** Error carrying the HTTP status used by API callers for safe UI branching. */
export class ApiError extends Error {
  /** @param {string} message @param {number} status */
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * @typedef {"quota" | "reference_photo_required" |
 * "illustration_provider_not_configured" | "safety_review_unavailable" |
 * "safety_provider_not_configured" | "unknown"} StoryCreateFailure
 */

/**
 * Classify API errors from story creation into typed failure categories.
 * Only accepts ApiError instances — arbitrary objects are not trusted.
 * @param {unknown} error
 * @returns {StoryCreateFailure}
 */
export function storyCreateFailure(error) {
  if (!(error instanceof ApiError)) return "unknown";
  if (error.status === 402) return "quota";
  if (error.status === 409) return "reference_photo_required";
  if (error.status !== 503) return "unknown";
  if (
    error.message === "illustration_provider_not_configured" ||
    error.message === "safety_review_unavailable" ||
    error.message === "safety_provider_not_configured"
  ) {
    return error.message;
  }
  return "unknown";
}

/**
 * Map failure type to the correct i18n message key.
 * @param {StoryCreateFailure} failure
 * @param {"dashboard" | "regeneration"} surface
 * @returns {string}
 */
export function storyCreateMessageKey(failure, surface) {
  if (failure === "quota") {
    return surface === "regeneration"
      ? "reader.regenerateLimitReached"
      : "child.limitReached";
  }
  if (failure === "reference_photo_required") {
    return surface === "regeneration"
      ? "reader.regeneratePhotoRequired"
      : "child.photoRequiredBody";
  }
  if (failure === "illustration_provider_not_configured") {
    return "generationErrors.providerNotConfigured";
  }
  if (failure === "safety_review_unavailable") {
    return "child.safetyReviewUnavailable";
  }
  if (failure === "safety_provider_not_configured") {
    return "child.safetyProviderNotConfigured";
  }
  return surface === "regeneration"
    ? "reader.regenerateFailed"
    : "child.generateFailed";
}
