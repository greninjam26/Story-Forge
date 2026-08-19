import assert from "node:assert/strict";
import test from "node:test";

const TOKEN_KEY = "storyforge-token";

function mockLocalStorage() {
  const store = {};
  return {
    getItem: (key) => store[key] ?? null,
    setItem: (key, value) => { store[key] = value; },
    removeItem: (key) => { delete store[key]; },
    get length() { return Object.keys(store).length; },
    clear: () => { for (const k of Object.keys(store)) delete store[k]; },
  };
}

test("localStorage persistence round-trip", () => {
  const ls = mockLocalStorage();
  const token = "eyJhbGciOiJIUzI1NiJ9.test";

  ls.setItem(TOKEN_KEY, token);
  assert.equal(ls.getItem(TOKEN_KEY), token);

  ls.removeItem(TOKEN_KEY);
  assert.equal(ls.getItem(TOKEN_KEY), null);
});

test("localStorage returns null when key absent", () => {
  const ls = mockLocalStorage();
  assert.equal(ls.getItem(TOKEN_KEY), null);
});

test("API URL defaults to /api", () => {
  const url = process.env.NEXT_PUBLIC_API_URL ?? "/api";
  assert.equal(url, "/api");
});
