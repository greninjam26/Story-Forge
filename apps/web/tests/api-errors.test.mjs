import assert from "node:assert/strict";
import test from "node:test";

// Inline ApiError to avoid importing .ts from .mjs
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function storyCreateFailure(error) {
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

function storyCreateMessageKey(failure, surface) {
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

test("classifies story-creation failures for localized UI handling", () => {
  assert.equal(storyCreateFailure(new ApiError("quota", 402)), "quota");
  assert.equal(
    storyCreateFailure(new ApiError("safety_review_unavailable", 503)),
    "safety_review_unavailable",
  );
  assert.equal(
    storyCreateFailure(new ApiError("safety_provider_not_configured", 503)),
    "safety_provider_not_configured",
  );
  assert.equal(
    storyCreateFailure(new ApiError("illustration_provider_not_configured", 503)),
    "illustration_provider_not_configured",
  );
  assert.equal(
    storyCreateFailure(new ApiError("photo required", 409)),
    "reference_photo_required",
  );
  assert.equal(
    storyCreateFailure(new ApiError("safety_review_unavailable", 500)),
    "unknown",
  );
  assert.equal(
    storyCreateFailure({ status: 503, message: "safety_review_unavailable" }),
    "unknown",
  );
  assert.equal(storyCreateFailure(new Error("private failure")), "unknown");
});

test("maps dashboard failures to localized message keys", () => {
  assert.equal(
    storyCreateMessageKey("quota", "dashboard"),
    "child.limitReached",
  );
  assert.equal(
    storyCreateMessageKey("reference_photo_required", "dashboard"),
    "child.photoRequiredBody",
  );
  assert.equal(
    storyCreateMessageKey("illustration_provider_not_configured", "dashboard"),
    "generationErrors.providerNotConfigured",
  );
  assert.equal(
    storyCreateMessageKey("safety_review_unavailable", "dashboard"),
    "child.safetyReviewUnavailable",
  );
  assert.equal(
    storyCreateMessageKey("safety_provider_not_configured", "dashboard"),
    "child.safetyProviderNotConfigured",
  );
  assert.equal(
    storyCreateMessageKey("unknown", "dashboard"),
    "child.generateFailed",
  );
});

test("maps regeneration failures to distinct localized message keys", () => {
  assert.equal(
    storyCreateMessageKey("quota", "regeneration"),
    "reader.regenerateLimitReached",
  );
  assert.equal(
    storyCreateMessageKey("reference_photo_required", "regeneration"),
    "reader.regeneratePhotoRequired",
  );
  assert.equal(
    storyCreateMessageKey("safety_review_unavailable", "regeneration"),
    "child.safetyReviewUnavailable",
  );
  assert.equal(
    storyCreateMessageKey("safety_provider_not_configured", "regeneration"),
    "child.safetyProviderNotConfigured",
  );
  assert.equal(
    storyCreateMessageKey("illustration_provider_not_configured", "regeneration"),
    "generationErrors.providerNotConfigured",
  );
  assert.equal(
    storyCreateMessageKey("unknown", "regeneration"),
    "reader.regenerateFailed",
  );
});
