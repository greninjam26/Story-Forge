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

function loadModules(t) {
  const tempDir = mkdtempSync(join(tmpdir(), "storyforge-delete-test-"));
  t.after(() => rmSync(tempDir, { recursive: true, force: true }));
  compileForTest("lib/story-create-errors.ts", join(tempDir, "story-create-errors.js"));
  compileForTest(
    "lib/account-deletion-errors.ts",
    join(tempDir, "account-deletion-errors.js"),
  );
  return {
    ...require(join(tempDir, "story-create-errors.js")),
    ...require(join(tempDir, "account-deletion-errors.js")),
  };
}

test("subscription cancellation failure gets specific account deletion copy", (t) => {
  const { ApiError, accountDeletionMessageKey } = loadModules(t);

  assert.equal(
    accountDeletionMessageKey(
      new ApiError("safe backend message", 503, "subscription_cancellation_failed"),
    ),
    "children.deleteAccountSubscriptionCancellationFailed",
  );
});

test("other account deletion failures retain the generic copy", (t) => {
  const { ApiError, accountDeletionMessageKey } = loadModules(t);

  assert.equal(
    accountDeletionMessageKey(new ApiError("unknown", 500)),
    "children.deleteAccountFailed",
  );
  assert.equal(
    accountDeletionMessageKey(new Error("offline")),
    "children.deleteAccountFailed",
  );
});
