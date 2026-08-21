import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);

function compileForTest(sourcePath, outputPath) {
  const source = readFileSync(sourcePath, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: sourcePath,
  });
  writeFileSync(outputPath, outputText);
}

function loadApiModule(tempDir) {
  compileForTest("lib/story-create-errors.ts", join(tempDir, "story-create-errors.js"));
  compileForTest("lib/api.ts", join(tempDir, "api.js"));
  return require(join(tempDir, "api.js"));
}

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

test("API requests restore a persisted token after a page reload", async (t) => {
  const tempDir = mkdtempSync(join(tmpdir(), "storyforge-api-test-"));
  const originalWindow = globalThis.window;
  const originalLocalStorage = globalThis.localStorage;
  const originalFetch = globalThis.fetch;
  const localStorage = memoryStorage();
  localStorage.setItem("storyforge-token", "persisted-token");
  globalThis.window = { localStorage };
  globalThis.localStorage = localStorage;

  t.after(() => {
    rmSync(tempDir, { recursive: true, force: true });
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
    if (originalLocalStorage === undefined) {
      delete globalThis.localStorage;
    } else {
      globalThis.localStorage = originalLocalStorage;
    }
  });

  let requestUrl;
  let requestHeaders;
  globalThis.fetch = async (url, init) => {
    requestUrl = url;
    requestHeaders = new Headers(init?.headers);
    return new Response("{}", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const { api } = loadApiModule(tempDir);
  await api.me();

  assert.equal(requestUrl, "/api/auth/me");
  assert.equal(requestHeaders.get("Authorization"), "Bearer persisted-token");
});

test("registration sends the selected French locale", async (t) => {
  const tempDir = mkdtempSync(join(tmpdir(), "storyforge-api-test-"));
  const originalWindow = globalThis.window;
  const originalLocalStorage = globalThis.localStorage;
  const originalFetch = globalThis.fetch;
  const localStorage = memoryStorage();
  globalThis.window = { localStorage };
  globalThis.localStorage = localStorage;

  t.after(() => {
    rmSync(tempDir, { recursive: true, force: true });
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
    if (originalLocalStorage === undefined) {
      delete globalThis.localStorage;
    } else {
      globalThis.localStorage = originalLocalStorage;
    }
  });

  let requestBody;
  globalThis.fetch = async (_url, init) => {
    requestBody = init?.body;
    return new Response('{"access_token":"token","token_type":"bearer"}', {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const { api } = loadApiModule(tempDir);
  await api.register("parent@example.com", "password123", "fr");

  assert.deepEqual(JSON.parse(requestBody), {
    email: "parent@example.com",
    password: "password123",
    locale: "fr",
  });
});
