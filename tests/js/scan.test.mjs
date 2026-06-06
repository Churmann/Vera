// Unit tests for the pure helpers in static/js/scan.js.
// Run with: node --test  (no extra dependencies).
//
// We only test the DOM-free helpers here. The camera/ZXing wiring is
// browser-only and deliberately kept thin (see scan.js).
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  normalizeBarcode,
  productUrl,
  cameraConstraints,
  preflightKind,
  errorKind,
  describeError,
} from "../../static/js/scan.js";

test("normalizeBarcode strips non-digits and accepts retail barcode lengths", () => {
  assert.equal(normalizeBarcode("3017620422003"), "3017620422003"); // EAN-13
  assert.equal(normalizeBarcode("  0123456789012 "), "0123456789012");
  assert.equal(normalizeBarcode("012345678905"), "012345678905"); // UPC-A (12)
  assert.equal(normalizeBarcode("96385074"), "96385074"); // EAN-8
  assert.equal(normalizeBarcode("0 0123456789012"), "00123456789012"); // GTIN-14 (14 digits)
  assert.equal(normalizeBarcode("4006381333931"), "4006381333931");
});

test("normalizeBarcode keeps the digits even when a scanner appends junk chars", () => {
  // ZXing returns clean digits, but the manual field is free text.
  assert.equal(normalizeBarcode("ean: 4006381333931"), "4006381333931");
});

test("normalizeBarcode rejects empty / wrong-length / non-digit input", () => {
  assert.equal(normalizeBarcode(""), null);
  assert.equal(normalizeBarcode("   "), null);
  assert.equal(normalizeBarcode("abc"), null);
  assert.equal(normalizeBarcode("123"), null); // too short
  assert.equal(normalizeBarcode("123456789012345"), null); // 15 digits, too long
  assert.equal(normalizeBarcode(null), null);
  assert.equal(normalizeBarcode(undefined), null);
});

test("productUrl builds the existing /product route and encodes the code", () => {
  assert.equal(productUrl("3017620422003"), "/product/3017620422003");
  // Defensive: even though normalizeBarcode yields digits, encode anyway.
  assert.equal(productUrl("12/34"), "/product/12%2F34");
});

test("cameraConstraints prefers the rear ('environment') camera", () => {
  const c = cameraConstraints();
  assert.deepEqual(c, { video: { facingMode: { ideal: "environment" } } });
});

test("preflightKind blocks insecure / unsupported contexts before touching the camera", () => {
  assert.equal(preflightKind({ secure: true, hasGetUserMedia: true }), null);
  assert.equal(preflightKind({ secure: false, hasGetUserMedia: true }), "insecure");
  assert.equal(preflightKind({ secure: true, hasGetUserMedia: false }), "unsupported");
  // Insecure takes precedence — it's the more actionable message.
  assert.equal(preflightKind({ secure: false, hasGetUserMedia: false }), "insecure");
});

test("errorKind maps getUserMedia DOMException names to our error kinds", () => {
  assert.equal(errorKind({ name: "NotAllowedError" }), "denied");
  assert.equal(errorKind({ name: "SecurityError" }), "denied");
  assert.equal(errorKind({ name: "NotFoundError" }), "no-camera");
  assert.equal(errorKind({ name: "OverconstrainedError" }), "no-camera");
  assert.equal(errorKind({ name: "DevicesNotFoundError" }), "no-camera");
  assert.equal(errorKind({ name: "NotReadableError" }), "in-use");
  assert.equal(errorKind({ name: "TrackStartError" }), "in-use");
  assert.equal(errorKind({ name: "WeirdNewError" }), "generic");
  assert.equal(errorKind(null), "generic");
});

test("describeError returns a clear, non-empty message for every kind", () => {
  for (const kind of ["denied", "no-camera", "insecure", "unsupported", "in-use", "load-failed", "generic"]) {
    const msg = describeError(kind);
    assert.equal(typeof msg, "string");
    assert.ok(msg.length > 0, `expected a message for ${kind}`);
  }
  // Unknown kinds still get the generic fallback, never undefined.
  assert.equal(describeError("nonsense"), describeError("generic"));
});
