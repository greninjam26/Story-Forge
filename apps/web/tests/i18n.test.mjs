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

test("exports English and French with English as the default", () => {
  assert.deepEqual(Array.from(LOCALES), ["en", "fr"]);
  assert.equal(DEFAULT_LOCALE, "en");
});

test("French catalog has every English message key", () => {
  assert.deepEqual(messageKeys(messages.fr), messageKeys(messages.en));
});

test("every locale includes accessible language and review failure messages", () => {
  for (const locale of LOCALES) {
    assert.equal(typeof messages[locale].children.storyLanguageLabel, "string");
    assert.equal(typeof messages[locale].reader.reviewFailed, "string");
  }
});
