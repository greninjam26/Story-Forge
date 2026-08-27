/** Error carrying the HTTP status used by API callers for safe UI branching. */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type StoryCreateFailure =
  | "quota"
  | "reference_photo_required"
  | "illustration_provider_not_configured"
  | "safety_review_unavailable"
  | "safety_provider_not_configured"
  | "unknown";

/** Classify API errors from story creation into typed failure categories. */
export function storyCreateFailure(error: unknown): StoryCreateFailure {
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

/** Map failure type to the correct i18n message key. */
function storyCreateMessageKey(
  failure: StoryCreateFailure,
  surface: "dashboard" | "regeneration",
): string {
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

type StoryCreateMessageContext =
  | { surface: "dashboard"; childName: string }
  | { surface: "regeneration" };

type StoryCreateMessage = {
  key: string;
  params?: Record<string, string | number>;
};

export function storyCreateMessage(
  failure: StoryCreateFailure,
  context: StoryCreateMessageContext,
): StoryCreateMessage {
  const key = storyCreateMessageKey(failure, context.surface);
  if (context.surface === "dashboard") {
    return { key, params: { name: context.childName } };
  }
  return { key };
}

/** Map a persisted background failure to safe parent-facing copy. */
export function storyFailureMessageKey(failureReason: string | null): string {
  if (failureReason === "story_generation_failed") {
    return "generationErrors.storyFailed";
  }
  if (failureReason === "illustration_generation_failed") {
    return "generationErrors.illustrationFailed";
  }
  if (failureReason === "narration_generation_failed") {
    return "generationErrors.narrationFailed";
  }
  if (failureReason === "safety_review_unavailable") {
    return "child.safetyReviewUnavailable";
  }
  if (failureReason === "background_generation_attempts_exhausted") {
    return "generationErrors.attemptsExhausted";
  }
  return "generationErrors.generic";
}

export function storyRecoveryMessage(error: unknown): { key: string } {
  if (!(error instanceof ApiError)) {
    return { key: "reader.recoveryFailed" };
  }
  if (error.status === 409) {
    if (error.message === "story_recovery_attempts_exhausted") {
      return { key: "reader.recoveryAttemptsExhausted" };
    }
    if (error.message === "Story is not generation failed.") {
      return { key: "reader.recoveryConflict" };
    }
    return { key: "reader.regeneratePhotoRequired" };
  }
  if (error.status !== 503) {
    return { key: "reader.recoveryFailed" };
  }
  const providerKeys: Record<string, string> = {
    story_provider_not_configured: "generationErrors.storyProviderNotConfigured",
    illustration_provider_not_configured: "generationErrors.providerNotConfigured",
    narration_provider_not_configured: "generationErrors.narrationProviderNotConfigured",
    safety_provider_not_configured: "child.safetyProviderNotConfigured",
    safety_review_unavailable: "child.safetyReviewUnavailable",
  };
  return { key: providerKeys[error.message] ?? "reader.recoveryFailed" };
}

export function storyGenerationStageMessageKey(stage: import("./types").GenerationStage): string {
  if (stage === "story_text" || stage === "moderation") {
    return "reader.stageStoryText";
  }
  if (stage === "illustrations") return "reader.stageIllustrations";
  if (stage === "narration") return "reader.stageNarration";
  return "reader.stageComplete";
}
