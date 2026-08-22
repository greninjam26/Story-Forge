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

function loadAuthSessionModule(tempDir) {
  try {
    compileForTest(
      "lib/story-create-errors.ts",
      join(tempDir, "story-create-errors.js"),
    );
    compileForTest("lib/api.ts", join(tempDir, "api.js"));
    compileForTest("lib/auth-session.ts", join(tempDir, "auth-session.js"));
    return require(join(tempDir, "auth-session.js"));
  } catch (error) {
    if (error?.code === "ENOENT") return {};
    throw error;
  }
}

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

function authSessionHarness(t, token) {
  const tempDir = mkdtempSync(join(tmpdir(), "storyforge-auth-session-test-"));
  const originalWindow = globalThis.window;
  const originalLocalStorage = globalThis.localStorage;
  const originalFetch = globalThis.fetch;
  const localStorage = memoryStorage();
  if (token) localStorage.setItem("storyforge-token", token);
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

  return {
    localStorage,
    session: loadAuthSessionModule(tempDir),
  };
}

test("starting an auth session restores the account locale", (t) => {
  const { localStorage, session } = authSessionHarness(t);
  const { startAuthSession } = session;
  assert.equal(typeof startAuthSession, "function");
  let activeLocale = "en";

  startAuthSession(
    {
      access_token: "returned-token",
      token_type: "bearer",
      locale: "fr",
    },
    (locale) => {
      activeLocale = locale;
    },
  );

  assert.equal(localStorage.getItem("storyforge-token"), "returned-token");
  assert.equal(activeLocale, "fr");
});

test("changing an authenticated locale persists it before updating the browser", async (t) => {
  const { session } = authSessionHarness(t, "persisted-token");

  let requestUrl;
  let requestMethod;
  let requestBody;
  globalThis.fetch = async (url, init) => {
    requestUrl = url;
    requestMethod = init?.method;
    requestBody = init?.body;
    return new Response(
      JSON.stringify({
        id: "7e12e4e2-ad15-4a0a-a9b5-32455b2dbf7b",
        email: "parent@example.com",
        locale: "fr",
        is_subscribed: false,
        free_stories_used: 0,
        free_stories_limit: 5,
        created_at: "2026-08-22T00:00:00Z",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  const { changeAccountLocale } = session;
  assert.equal(typeof changeAccountLocale, "function");
  let activeLocale = "en";

  const changed = await changeAccountLocale("fr", (locale) => {
    activeLocale = locale;
  });

  assert.equal(changed, true);
  assert.equal(requestUrl, "/api/auth/me");
  assert.equal(requestMethod, "PATCH");
  assert.deepEqual(JSON.parse(requestBody), { locale: "fr" });
  assert.equal(activeLocale, "fr");
});

test("a failed account locale save keeps the current browser locale", async (t) => {
  const { session } = authSessionHarness(t, "persisted-token");

  globalThis.fetch = async () =>
    new Response('{"detail":"Save failed."}', {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });

  const { changeAccountLocale } = session;
  let activeLocale = "en";

  const changed = await changeAccountLocale("fr", (locale) => {
    activeLocale = locale;
  });

  assert.equal(changed, false);
  assert.equal(activeLocale, "en");
});

test("an expired session is cleared before changing locale locally", async (t) => {
  const { localStorage, session } = authSessionHarness(t, "expired-token");

  globalThis.fetch = async () =>
    new Response('{"detail":"Could not validate credentials."}', {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });

  const { changeAccountLocale } = session;
  let activeLocale = "en";

  const changed = await changeAccountLocale("fr", (locale) => {
    activeLocale = locale;
  });

  assert.equal(changed, true);
  assert.equal(localStorage.getItem("storyforge-token"), null);
  assert.equal(activeLocale, "fr");
});
