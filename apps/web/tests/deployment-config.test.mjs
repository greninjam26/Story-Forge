import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadSecurityHeadersModule() {
  const source = readFileSync(
    new URL("../lib/security-headers.ts", import.meta.url),
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

test("production headers allow the Google sign-in popup to communicate", () => {
  const { buildSecurityHeaders } = loadSecurityHeadersModule();
  const headers = new Map(
    buildSecurityHeaders("production").map((header) => [
      header.key.toLowerCase(),
      header.value,
    ]),
  );

  assert.equal(
    headers.get("cross-origin-opener-policy"),
    "same-origin-allow-popups",
  );
});

test("Vercel config leaves browser security headers to Next.js", () => {
  const config = JSON.parse(readFileSync("vercel.json", "utf8"));

  assert.equal(config.framework, "nextjs");
  assert.deepEqual(config.regions, ["iad1"]);
  assert.equal("headers" in config, false);
});
