import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadAnalyticsPrivacyModule() {
  const source = readFileSync(
    new URL("../lib/analytics-privacy.ts", import.meta.url),
    "utf8",
  );
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const commonJsModule = { exports: {} };

  vm.runInNewContext(output, {
    exports: commonJsModule.exports,
    module: commonJsModule,
  });
  return commonJsModule.exports;
}

test("analytics page views omit UUIDs and URL metadata", () => {
  const { redactAnalyticsEvent } = loadAnalyticsPrivacyModule();
  const event = {
    type: "pageview",
    url:
      "https://story-forge-bice.vercel.app/reader/" +
      "53fd612e-5bec-4b1f-b0d2-2997ae3a28bb/stories/" +
      "a1797828-b296-4ca4-af84-3a58440361da?token=secret#page-2",
  };

  const redacted = redactAnalyticsEvent(event);

  assert.equal(
    redacted.url,
    "https://story-forge-bice.vercel.app/reader/[id]/stories/[id]",
  );
  assert.equal(event.url.includes("53fd612e-5bec-4b1f-b0d2-2997ae3a28bb"), true);
});

test("analytics preserves non-identifying public paths", () => {
  const { redactAnalyticsEvent } = loadAnalyticsPrivacyModule();

  const redacted = redactAnalyticsEvent({
    type: "pageview",
    url: "https://story-forge-bice.vercel.app/privacy",
  });

  assert.equal(redacted.url, "https://story-forge-bice.vercel.app/privacy");
});
