import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("production headers allow the Google sign-in popup to communicate", () => {
  const config = JSON.parse(readFileSync("vercel.json", "utf8"));
  const headers = new Map(
    config.headers
      .flatMap((route) => route.headers)
      .map((header) => [header.key.toLowerCase(), header.value]),
  );

  assert.equal(
    headers.get("cross-origin-opener-policy"),
    "same-origin-allow-popups",
  );
});
