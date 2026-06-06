// Unit tests for the pure helpers in static/js/history.js.
// Run with: node --test  (no extra dependencies).
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  computeBand,
  applyEntry,
  countByBand,
  formatRelativeTime,
  createSafeStorage,
} from "../../static/js/history.js";

test("computeBand uses the product page thresholds", () => {
  assert.equal(computeBand(100), "good");
  assert.equal(computeBand(70), "good");
  assert.equal(computeBand(69), "mixed");
  assert.equal(computeBand(40), "mixed");
  assert.equal(computeBand(39), "poor");
  assert.equal(computeBand(0), "poor");
});

test("applyEntry dedupes by id and moves the re-viewed product to the top", () => {
  const entries = [
    { id: "a", viewedAt: 3 },
    { id: "b", viewedAt: 2 },
    { id: "c", viewedAt: 1 },
  ];
  const result = applyEntry(entries, { id: "c", viewedAt: 4 });
  assert.deepEqual(result.map((e) => e.id), ["c", "a", "b"]);
  assert.equal(result.length, 3); // no duplicate "c"
});

test("applyEntry caps the list length, keeping the newest", () => {
  const entries = [{ id: "a" }, { id: "b" }, { id: "c" }];
  const result = applyEntry(entries, { id: "d" }, 3);
  assert.deepEqual(result.map((e) => e.id), ["d", "a", "b"]);
});

test("countByBand tallies grades and total", () => {
  const counts = countByBand([
    { band: "good" },
    { band: "good" },
    { band: "mixed" },
    { band: "poor" },
  ]);
  assert.deepEqual(counts, { good: 2, mixed: 1, poor: 1, total: 4 });
});

test("formatRelativeTime renders friendly relative strings", () => {
  const now = 1_000_000_000_000;
  assert.equal(formatRelativeTime(now - 5_000, now), "just now");
  assert.equal(formatRelativeTime(now - 60_000, now), "1 minute ago");
  assert.equal(formatRelativeTime(now - 120_000, now), "2 minutes ago");
  assert.equal(formatRelativeTime(now - 2 * 86_400_000, now), "2 days ago");
});

test("createSafeStorage falls back to memory when storage throws", () => {
  const throwing = {
    setItem() {
      throw new Error("blocked");
    },
    getItem() {
      throw new Error("blocked");
    },
    removeItem() {},
  };
  const safe = createSafeStorage(throwing);
  assert.equal(safe.available, false);
  // The in-memory fallback still works as a key/value store.
  safe.store.setItem("k", "v");
  assert.equal(safe.store.getItem("k"), "v");
});
