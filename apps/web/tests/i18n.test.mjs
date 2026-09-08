import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadMessageModule() {
  const source = fs.readFileSync(
    new URL("../lib/messages.ts", import.meta.url),
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

function messageKeys(catalog, prefix = "") {
  return Object.entries(catalog).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === "string" ? [path] : messageKeys(value, path);
  });
}

const { DEFAULT_LOCALE, LOCALES, messages } = loadMessageModule();

const requiredPrivacyKeys = [
  "purposesHeading",
  "purposes",
  "providersHeading",
  "providersIntro",
  "providersStory",
  "providersModeration",
  "providersImages",
  "providersNarration",
  "providersAuthentication",
  "providersBilling",
  "providersInfrastructure",
  "readerHeading",
  "readerAccess",
  "readerReset",
  "readerIndexing",
  "retentionHeading",
  "retentionRecords",
  "retentionBillingAudit",
  "retentionAssets",
  "deletionHeading",
  "deletionControls",
  "deletionBilling",
  "analyticsHeading",
  "analyticsRedaction",
  "analyticsOptOut",
  "contact",
  "contactEmail",
  "contactTemporary",
];

test("exports English and French with English as the default", () => {
  assert.deepEqual(Array.from(LOCALES), ["en", "fr"]);
  assert.equal(DEFAULT_LOCALE, "en");
});

test("French catalog has every English message key", () => {
  assert.deepEqual(messageKeys(messages.fr), messageKeys(messages.en));
});

test("every locale includes language and save failure messages", () => {
  for (const locale of LOCALES) {
    assert.equal(typeof messages[locale].auth.localeSaveFailed, "string");
    assert.equal(typeof messages[locale].children.storyLanguageLabel, "string");
    assert.equal(typeof messages[locale].reader.reviewFailed, "string");
    assert.equal(typeof messages[locale].auth.googleUnavailable, "string");
    assert.equal(typeof messages[locale].auth.googleLinkPrompt, "string");
    assert.equal(typeof messages[locale].auth.googleConflict, "string");
    assert.equal(typeof messages[locale].child.readerAccessTitle, "string");
    assert.equal(typeof messages[locale].child.openReader, "string");
    assert.equal(typeof messages[locale].child.copyReaderLink, "string");
    assert.equal(typeof messages[locale].child.resetReaderLink, "string");
    assert.equal(
      typeof messages[locale].children
        .deleteAccountSubscriptionCancellationFailed,
      "string",
    );
  }
});

test("every locale includes the complete privacy disclosure catalog", () => {
  for (const locale of LOCALES) {
    for (const key of requiredPrivacyKeys) {
      assert.equal(
        typeof messages[locale].privacy[key],
        "string",
        `${locale}.privacy.${key}`,
      );
      assert.ok(
        messages[locale].privacy[key].trim().length > 0,
        `${locale}.privacy.${key} must not be blank`,
      );
    }
    assert.equal(
      messages[locale].privacy.contactEmail,
      "privacy@storyforge.invalid",
    );
  }

  assert.match(messages.en.privacy.contactTemporary, /unmonitored/i);
  assert.match(messages.fr.privacy.contactTemporary, /non surveillée/i);
});

test("privacy page renders every disclosure and a mailto contact", () => {
  const source = fs.readFileSync(
    new URL("../app/privacy/page.tsx", import.meta.url),
    "utf8",
  );

  for (const key of requiredPrivacyKeys) {
    assert.ok(
      source.includes(`t("privacy.${key}")`),
      `privacy page must render privacy.${key}`,
    );
  }
  assert.ok(source.includes('href={`mailto:${t("privacy.contactEmail")}`}'));
});
