import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiError,
  storyCreateFailure,
  storyCreateMessageKey,
} from "../lib/story-create-errors.mjs";

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
