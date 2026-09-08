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
    // The module runs in Next.js under Node, where URL is a global. The bare
    // sandbox has no globals of its own, so provide the ones it relies on.
    URL,
  });
  return commonJsModule.exports;
}

function asHeaderMap(headers) {
  return new Map(headers.map(({ key, value }) => [key.toLowerCase(), value]));
}

function asDirectiveMap(policy) {
  return new Map(
    policy.split(";").map((directive) => {
      const [name, ...values] = directive.trim().split(/\s+/);
      return [name, values];
    }),
  );
}

test("production CSP restricts ambient authority and allows current integrations", () => {
  const { buildSecurityHeaders } = loadSecurityHeadersModule();
  const headers = asHeaderMap(buildSecurityHeaders("production"));
  const csp = asDirectiveMap(headers.get("content-security-policy"));

  assert.deepEqual(csp.get("default-src"), ["'self'"]);
  assert.deepEqual(csp.get("base-uri"), ["'self'"]);
  assert.deepEqual(csp.get("object-src"), ["'none'"]);
  assert.deepEqual(csp.get("frame-ancestors"), ["'none'"]);
  assert.deepEqual(csp.get("form-action"), ["'self'"]);

  assert.ok(csp.get("script-src").includes("https://accounts.google.com"));
  assert.ok(csp.get("frame-src").includes("https://accounts.google.com"));
  assert.ok(csp.get("style-src").includes("https://accounts.google.com"));
  assert.ok(csp.get("script-src").includes("https://va.vercel-scripts.com"));
  assert.ok(csp.get("connect-src").includes("https://vitals.vercel-insights.com"));

  assert.ok(csp.get("img-src").includes("https:"));
  assert.ok(csp.get("img-src").includes("data:"));
  assert.ok(csp.get("img-src").includes("blob:"));
  assert.ok(csp.get("media-src").includes("https:"));
  assert.ok(csp.get("media-src").includes("data:"));
  assert.ok(csp.get("media-src").includes("blob:"));

  assert.ok(csp.has("upgrade-insecure-requests"));
  assert.ok(!csp.get("script-src").includes("'unsafe-eval'"));
});

test("development CSP permits local tooling without upgrading HTTP media", () => {
  const { buildSecurityHeaders } = loadSecurityHeadersModule();
  const headers = asHeaderMap(buildSecurityHeaders("development"));
  const csp = asDirectiveMap(headers.get("content-security-policy"));

  assert.ok(!csp.has("upgrade-insecure-requests"));
  assert.ok(csp.get("script-src").includes("'unsafe-eval'"));
});

test("the configured media origin is allowed for images and audio", () => {
  const { buildSecurityHeaders } = loadSecurityHeadersModule();
  const headers = asHeaderMap(
    buildSecurityHeaders("production", "https://api.example.com"),
  );
  const csp = asDirectiveMap(headers.get("content-security-policy"));

  assert.ok(csp.get("img-src").includes("https://api.example.com"));
  assert.ok(csp.get("media-src").includes("https://api.example.com"));
  assert.ok(csp.has("upgrade-insecure-requests"));
});

test("an HTTP media origin is allowed and never force-upgraded", () => {
  const { buildSecurityHeaders } = loadSecurityHeadersModule();
  const headers = asHeaderMap(
    buildSecurityHeaders("production", "http://127.0.0.1:8100"),
  );
  const csp = asDirectiveMap(headers.get("content-security-policy"));

  // Placeholder illustrations and narration are served over plain HTTP from
  // the API during local development and the offline end-to-end run.
  // `upgrade-insecure-requests` would rewrite them to an https:// port that is
  // not listening, so the image and audio elements would silently fail.
  assert.ok(csp.get("img-src").includes("http://127.0.0.1:8100"));
  assert.ok(csp.get("media-src").includes("http://127.0.0.1:8100"));
  assert.ok(!csp.has("upgrade-insecure-requests"));
});

test("a malformed media origin cannot weaken or inject into the policy", () => {
  const { buildSecurityHeaders } = loadSecurityHeadersModule();
  const headers = asHeaderMap(
    buildSecurityHeaders("production", "not-a-url; script-src *"),
  );
  const csp = asDirectiveMap(headers.get("content-security-policy"));

  assert.deepEqual(csp.get("img-src"), ["'self'", "https:", "data:", "blob:"]);
  assert.deepEqual(csp.get("script-src").includes("*"), false);
  assert.ok(csp.has("upgrade-insecure-requests"));
});

test("browser headers minimize capability URL exposure and isolate the app", () => {
  const { buildSecurityHeaders } = loadSecurityHeadersModule();
  const headers = asHeaderMap(buildSecurityHeaders("production"));

  assert.equal(headers.get("referrer-policy"), "no-referrer");
  assert.equal(headers.get("x-content-type-options"), "nosniff");
  assert.equal(headers.get("x-frame-options"), "DENY");
  assert.equal(
    headers.get("cross-origin-opener-policy"),
    "same-origin-allow-popups",
  );
  assert.match(headers.get("permissions-policy"), /camera=\(\)/);
  assert.match(headers.get("permissions-policy"), /microphone=\(\)/);
  assert.match(headers.get("permissions-policy"), /geolocation=\(\)/);
});

test("reader header rules prevent indexing and archival", () => {
  const { buildSecurityHeaderRules } = loadSecurityHeadersModule();
  const rules = buildSecurityHeaderRules("production");
  const readerRule = rules.find(({ source }) => source === "/reader/:path*");

  assert.ok(readerRule);
  assert.equal(
    asHeaderMap(readerRule.headers).get("x-robots-tag"),
    "noindex, nofollow, noarchive",
  );
});
