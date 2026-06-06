// Client-side barcode scanning for the Vera app.
//
// The /scan page opens the device camera and decodes a product barcode with
// ZXing (loaded as a UMD global, `window.ZXingBrowser`). On a successful read
// we redirect to the existing /product/{barcode} route, which scores it with
// the normal engine (and history is auto-logged there by history.js).
//
// Like history.js, this is an ES module used directly in the browser AND
// importable in Node for unit tests: the pure helpers below touch no DOM, and
// the camera glue is guarded so importing never requires a `document`/`window`.

// --- Pure helpers (no DOM, no camera) --------------------------------------

// Retail product barcodes are EAN-8, UPC-A (12), EAN-13, and GTIN-14.
const VALID_LENGTHS = new Set([8, 12, 13, 14]);

// Strip everything but digits, then accept only real barcode lengths. Used to
// sanitise the manual-entry field; ZXing results are already clean digits and
// pass straight through. Returns the clean code or null.
export function normalizeBarcode(raw) {
  if (raw == null) return null;
  const digits = String(raw).replace(/\D/g, "");
  return VALID_LENGTHS.has(digits.length) ? digits : null;
}

// The existing scoring route. Encode defensively even though codes are digits.
export function productUrl(code) {
  return `/product/${encodeURIComponent(code)}`;
}

// Prefer the rear camera on phones; `ideal` (not `exact`) so laptops with only
// a front camera still work instead of throwing OverconstrainedError.
export function cameraConstraints() {
  return { video: { facingMode: { ideal: "environment" } } };
}

// Decide, before touching the camera, whether we even can. getUserMedia needs
// a secure context (HTTPS or localhost) and browser support.
export function preflightKind({ secure, hasGetUserMedia }) {
  if (!secure) return "insecure";
  if (!hasGetUserMedia) return "unsupported";
  return null;
}

// Map a getUserMedia / camera DOMException to one of our error kinds.
export function errorKind(err) {
  switch (err && err.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "denied";
    case "NotFoundError":
    case "OverconstrainedError":
    case "DevicesNotFoundError":
      return "no-camera";
    case "NotReadableError":
    case "TrackStartError":
      return "in-use";
    default:
      return "generic";
  }
}

const MESSAGES = {
  denied:
    "Camera access was blocked. Allow camera access in your browser, then reload — or type the barcode below.",
  "no-camera":
    "No camera was found on this device. You can type the barcode below or search by name instead.",
  insecure:
    "Scanning needs a secure connection (HTTPS or localhost). Type the barcode below, or open the site over HTTPS to scan.",
  unsupported:
    "This browser can't open the camera for scanning. Type the barcode below, or try a different browser.",
  "in-use":
    "The camera looks busy in another app or tab. Close it and reload — or type the barcode below.",
  "load-failed":
    "The barcode scanner library couldn't load (check your network or any ad/script blocker). You can type the barcode below.",
  generic:
    "Something went wrong starting the camera. Reload to try again, or type the barcode below.",
};

// Always returns a non-empty string; unknown kinds fall back to generic.
export function describeError(kind) {
  return MESSAGES[kind] || MESSAGES.generic;
}

// --- Camera / ZXing glue (guarded so the module imports cleanly in Node) ---

const hasDom = typeof document !== "undefined";

// How long we wait, while the camera is live and finding nothing, before
// nudging the viewer toward the manual fallback.
const NO_DETECTION_NUDGE_MS = 25000;

function go(url) {
  window.location.assign(url);
}

// Breadcrumb logging so the decode pipeline is traceable in devtools. Cheap,
// quiet, and invaluable when the camera path misbehaves on a real device.
function log(...args) {
  if (typeof console !== "undefined") console.log("[scan]", ...args);
}

function initScanPage() {
  const root = document.getElementById("scan");
  if (!root) return;

  const video = document.getElementById("scan-video");
  const statusEl = document.getElementById("scan-status");
  const errorEl = document.getElementById("scan-error");
  const viewport = document.getElementById("scan-viewport");
  const manualForm = document.getElementById("scan-manual-form");
  const manualInput = document.getElementById("scan-manual-input");
  const manualError = document.getElementById("scan-manual-error");

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  // Show a friendly error, stop pretending the camera is coming, and lean on
  // the manual fallback (which is always present in the markup).
  function fail(kind) {
    log("fail:", kind);
    if (viewport) viewport.hidden = true;
    setStatus("");
    if (errorEl) {
      errorEl.textContent = describeError(kind);
      errorEl.hidden = false;
    }
    if (manualInput) manualInput.focus();
  }

  // Turn otherwise-silent uncaught errors (a bad API call, a thrown decoder
  // exception) into something the viewer can actually see, instead of failing
  // quietly to the console. This is what makes the page debuggable in the wild.
  function surfaceUnexpected(label, detail) {
    log("unexpected:", label, detail);
    if (errorEl && errorEl.hidden) {
      errorEl.textContent = describeError("generic");
      errorEl.hidden = false;
    }
    setStatus("");
  }
  window.addEventListener("error", (e) => surfaceUnexpected("error", e.message));
  window.addEventListener("unhandledrejection", (e) =>
    surfaceUnexpected("unhandledrejection", e.reason && e.reason.message)
  );

  // Prove the module is executing the moment we wire up — if the viewer sees
  // nothing here, scan.js itself never ran.
  setStatus("Initializing scanner…");
  log("init: module running, DOM wired");

  // Wire the manual-entry fallback regardless of camera outcome.
  if (manualForm) {
    manualForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const code = normalizeBarcode(manualInput ? manualInput.value : "");
      if (!code) {
        if (manualError) manualError.hidden = false;
        return;
      }
      if (manualError) manualError.hidden = true;
      go(productUrl(code));
    });
  }

  const preflight = preflightKind({
    secure: window.isSecureContext,
    hasGetUserMedia: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
  });
  if (preflight) {
    fail(preflight);
    return;
  }
  // The CDN script sets this flag via its onerror handler if it fails to load
  // (network blocked, SRI mismatch, ad-blocker). Distinguish that from a
  // generic failure so the message is actionable.
  if (window.__zxingLoadFailed || typeof window.ZXingBrowser === "undefined") {
    fail("load-failed");
    return;
  }

  setStatus("Starting camera…");
  log("zxing loaded; requesting camera");

  const reader = new window.ZXingBrowser.BrowserMultiFormatReader();
  let controls = null;
  let done = false;

  function stop() {
    if (controls) {
      try {
        controls.stop();
      } catch (_e) {
        /* already stopped */
      }
      controls = null;
    }
  }

  // Release the camera when leaving the page (back button, navigation).
  window.addEventListener("pagehide", stop);

  // Gentle nudge if we've been scanning a while with no hit.
  const nudge = setTimeout(() => {
    if (!done) setStatus("Still looking… make sure the barcode is well lit, or type it below.");
  }, NO_DETECTION_NUDGE_MS);

  reader
    .decodeFromConstraints(cameraConstraints(), video, (result, err) => {
      // The callback fires after every frame: `result` on a hit, `err` (almost
      // always a per-frame NotFoundException) otherwise. We act only on a real
      // decode and ignore the routine not-found noise — but log anything that
      // isn't NotFound, since that's a genuine signal worth seeing.
      if (result && !done) {
        const text = result.getText();
        log("decoded:", text);
        done = true;
        clearTimeout(nudge);
        stop();
        const code = normalizeBarcode(text);
        go(productUrl(code || text));
      } else if (err && err.name && err.name !== "NotFoundException") {
        log("decode error:", err.name, err.message);
      }
    })
    .then((c) => {
      controls = c;
      // The promise resolves once the stream is live and the decode loop is
      // running — this is the definitive "scanning has started" signal.
      setStatus("Scanning… point your camera at a barcode.");
      log("decode loop started");
    })
    .catch((err) => {
      clearTimeout(nudge);
      log("camera start failed:", err && err.name, err && err.message);
      fail(errorKind(err));
    });
}

if (hasDom) {
  // A module script is deferred, so the DOM is usually parsed by the time it
  // runs and DOMContentLoaded may have already fired — handle both cases.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initScanPage);
  } else {
    initScanPage();
  }
}
