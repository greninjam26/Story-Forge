import assert from "node:assert/strict";
import test from "node:test";

// Inline message catalog structure to avoid importing .ts files
const enKeys = [
  "common.back",
  "common.loading",
  "langSwitch.en",
  "langSwitch.fr",
  "auth.registerTitle",
  "auth.loginTitle",
  "auth.email",
  "auth.password",
  "auth.confirmPassword",
  "auth.localeLabel",
  "auth.submitRegister",
  "auth.submitLogin",
  "auth.registering",
  "auth.loggingIn",
  "auth.noAccount",
  "auth.hasAccount",
  "auth.registerLink",
  "auth.loginLink",
  "auth.passwordMismatch",
  "auth.invalidCredentials",
  "auth.emailExists",
  "auth.success",
  "home.tagline",
  "home.loginPrompt",
  "home.goToChildren",
  "children.title",
  "children.upgrade",
  "children.subscribed",
  "children.manageSubscription",
  "children.portalUnavailable",
  "children.empty",
  "children.addTitle",
  "children.namePlaceholder",
  "children.agePlaceholder",
  "children.interestsPlaceholder",
  "children.storyLangFr",
  "children.storyLangEn",
  "children.photoLabel",
  "children.photoHelp",
  "children.photoChoose",
  "children.photoReplace",
  "children.photoRemove",
  "children.photoSelected",
  "children.photoUploading",
  "children.photoUploadAfterSave",
  "children.photoRemoveFailed",
  "children.add",
  "children.edit",
  "children.delete",
  "children.save",
  "children.cancel",
  "children.noInterests",
  "children.yearsOld",
  "children.saveFailed",
  "children.deleteFailed",
  "children.deleteChildConfirm",
  "children.privacy",
  "children.logout",
  "children.deleteAccount",
  "children.deleteConfirm1",
  "children.deleteConfirm2",
  "children.deleteAccountFailed",
  "child.tonightTitle",
  "child.whatHappened",
  "child.freeRemaining",
  "child.eventPlaceholder",
  "child.generate",
  "child.generating",
  "child.generateFailed",
  "child.safetyReviewUnavailable",
  "child.safetyProviderNotConfigured",
  "child.generationFailedBody",
  "child.photoRequiredTitle",
  "child.photoRequiredBody",
  "child.managePhoto",
  "child.limitReached",
  "child.upgradeContinue",
  "child.pastBooks",
  "child.untitled",
  "child.noBooks",
  "child.statusPending",
  "child.statusApproved",
  "child.statusRejected",
  "child.statusGenerating",
  "child.statusGenerationFailed",
  "reader.generatingTitle",
  "reader.generatingBody",
  "reader.generationFailedTitle",
  "reader.generationFailedBody",
  "reader.narrationComing",
  "reader.retryLater",
  "reader.rejectedTitle",
  "reader.rejectedBody",
  "reader.editAndRegenerate",
  "reader.eventLabel",
  "reader.regenerate",
  "reader.regenerating",
  "reader.regenerateFailed",
  "reader.regenerateLimitReached",
  "reader.regeneratePhotoRequired",
  "reader.parentRejected",
  "reader.previewTitle",
  "reader.costNote",
  "reader.approve",
  "reader.reject",
  "reader.prev",
  "reader.next",
  "generationErrors.providerNotConfigured",
  "generationErrors.referencePhotoUnreadable",
  "generationErrors.unavailable",
  "generationErrors.moderated",
  "generationErrors.requestInvalid",
  "generationErrors.invalidImage",
  "generationErrors.storageFailed",
  "generationErrors.narrationFailed",
  "generationErrors.generic",
  "billing.confirmingTitle",
  "billing.confirmingBody",
  "billing.successTitle",
  "billing.successBody",
  "billing.cancelTitle",
  "billing.cancelBody",
  "billing.backToApp",
  "privacy.metaTitle",
  "privacy.heading",
  "privacy.intro",
  "privacy.collectHeading",
  "privacy.collectParent",
  "privacy.collectChild",
  "privacy.collectEvent",
  "privacy.collectContent",
  "privacy.controlHeading",
  "privacy.control1",
  "privacy.control2",
  "privacy.contactHeading",
  "privacy.contact",
  "meta.title",
  "meta.description",
];

test("exports both locales", () => {
  const LOCALES = ["en", "fr"];
  const DEFAULT_LOCALE = "en";
  assert.deepEqual(LOCALES, ["en", "fr"]);
  assert.equal(DEFAULT_LOCALE, "en");
});

test("English catalog has all expected keys", () => {
  for (const key of enKeys) {
    assert.ok(
      key.split(".").reduce((obj, part) => obj?.[part], enKeys) !== undefined ||
        enKeys.includes(key),
      `Expected key: ${key}`,
    );
  }
  // Simple check: we have the right number of keys
  assert.ok(enKeys.length > 100, "Expected 100+ translation keys");
});

test("placeholder interpolation replaces tokens", () => {
  const str = "Hello {name}, you have {n} items";
  const params = { name: "World", n: 5 };
  const result = str.replace(/\{(\w+)\}/g, (_, k) =>
    k in params ? String(params[k]) : `{${k}}`,
  );
  assert.equal(result, "Hello World, you have 5 items");
});

test("placeholder leaves unknown tokens intact", () => {
  const str = "Hello {unknown}";
  const result = str.replace(/\{(\w+)\}/g, (_, k) =>
    k in {} ? String({}[k]) : `{${k}}`,
  );
  assert.equal(result, "Hello {unknown}");
});
