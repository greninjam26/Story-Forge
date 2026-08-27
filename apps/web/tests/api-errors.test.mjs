import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadStoryCreateErrors() {
  const source = fs.readFileSync(
    new URL("../lib/story-create-errors.ts", import.meta.url),
    "utf8",
  );
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const exports = {};
  const commonJsModule = { exports };
  vm.runInNewContext(output, { exports, module: commonJsModule });
  return commonJsModule.exports;
}

const {
  ApiError,
  storyCreateFailure,
  storyCreateMessage,
  storyFailureMessageKey,
  storyGenerationStageMessageKey,
  storyRecoveryMessage,
} = loadStoryCreateErrors();

test("maps persisted safety-review failures without exposing internal codes", () => {
  assert.equal(
    storyFailureMessageKey("safety_review_unavailable"),
    "child.safetyReviewUnavailable",
  );
  assert.equal(
    storyFailureMessageKey("background_generation_attempts_exhausted"),
    "generationErrors.attemptsExhausted",
  );
  assert.equal(storyFailureMessageKey(null), "generationErrors.generic");
});

test("maps failed-story recovery errors and generation stages", () => {
  assert.equal(
    storyRecoveryMessage(new ApiError("Story is not generation failed.", 409)).key,
    "reader.recoveryConflict",
  );
  assert.equal(
    storyRecoveryMessage(new ApiError("story_recovery_attempts_exhausted", 409)).key,
    "reader.recoveryAttemptsExhausted",
  );
  assert.equal(storyRecoveryMessage(new Error("private")).key, "reader.recoveryFailed");
  assert.equal(storyGenerationStageMessageKey("illustrations"), "reader.stageIllustrations");
  assert.equal(storyGenerationStageMessageKey("narration"), "reader.stageNarration");
});

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

test("maps dashboard failures to localized messages with child names", () => {
  const expectedKeys = {
    quota: "child.limitReached",
    reference_photo_required: "child.photoRequiredBody",
    illustration_provider_not_configured: "generationErrors.providerNotConfigured",
    safety_review_unavailable: "child.safetyReviewUnavailable",
    safety_provider_not_configured: "child.safetyProviderNotConfigured",
    unknown: "child.generateFailed",
  };
  for (const [failure, key] of Object.entries(expectedKeys)) {
    const message = storyCreateMessage(failure, {
      surface: "dashboard",
      childName: "Camille",
    });
    assert.equal(message.key, key);
    assert.equal(message.params.name, "Camille");
  }
});

test("maps regeneration failures to distinct localized message keys", () => {
  const expectedKeys = {
    quota: "reader.regenerateLimitReached",
    reference_photo_required: "reader.regeneratePhotoRequired",
    safety_review_unavailable: "child.safetyReviewUnavailable",
    safety_provider_not_configured: "child.safetyProviderNotConfigured",
    illustration_provider_not_configured: "generationErrors.providerNotConfigured",
    unknown: "reader.regenerateFailed",
  };
  for (const [failure, key] of Object.entries(expectedKeys)) {
    const message = storyCreateMessage(failure, {
      surface: "regeneration",
    });
    assert.equal(message.key, key);
    assert.equal(message.params, undefined);
  }
});
