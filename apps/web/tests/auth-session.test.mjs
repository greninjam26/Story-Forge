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

test("starting an auth session restores the account locale", (t) => {
  const tempDir = mkdtempSync(join(tmpdir(), "storyforge-auth-session-test-"));
  const originalWindow = globalThis.window;
  const originalLocalStorage = globalThis.localStorage;
  const localStorage = memoryStorage();
  globalThis.window = { localStorage };
  globalThis.localStorage = localStorage;

  t.after(() => {
    rmSync(tempDir, { recursive: true, force: true });
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

  const { startAuthSession } = loadAuthSessionModule(tempDir);
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
