import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);

function loadPollingModule(tempDir) {
  try {
    const source = readFileSync("lib/polling.ts", "utf8");
    const { outputText } = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2020,
      },
      fileName: "lib/polling.ts",
    });
    const outputPath = join(tempDir, "polling.js");
    writeFileSync(outputPath, outputText);
    return require(outputPath);
  } catch (error) {
    if (error?.code === "ENOENT") return {};
    throw error;
  }
}

test("polling stops after delivering a terminal value", async (t) => {
  const tempDir = mkdtempSync(join(tmpdir(), "storyforge-polling-test-"));
  t.after(() => rmSync(tempDir, { recursive: true, force: true }));
  const { startPolling } = loadPollingModule(tempDir);
  assert.equal(typeof startPolling, "function");

  const values = ["generating", "pending_review"];
  const delivered = [];
  let loads = 0;
  await new Promise((resolve, reject) => {
    startPolling({
      load: async () => {
        loads += 1;
        return values.shift();
      },
      shouldContinue: (value) => value === "generating",
      onValue: (value) => {
        delivered.push(value);
        if (value === "pending_review") resolve();
      },
      onError: reject,
      intervalMs: 0,
    });
  });

  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.deepEqual(delivered, ["generating", "pending_review"]);
  assert.equal(loads, 2);
});

test("cancelling polling ignores an in-flight result", async (t) => {
  const tempDir = mkdtempSync(join(tmpdir(), "storyforge-polling-test-"));
  t.after(() => rmSync(tempDir, { recursive: true, force: true }));
  const { startPolling } = loadPollingModule(tempDir);
  assert.equal(typeof startPolling, "function");

  let finishLoad;
  const delivered = [];
  const stop = startPolling({
    load: () => new Promise((resolve) => {
      finishLoad = resolve;
    }),
    shouldContinue: () => true,
    onValue: (value) => delivered.push(value),
    onError: assert.fail,
    intervalMs: 0,
  });

  stop();
  finishLoad("generating");
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.deepEqual(delivered, []);
});
