// Client-side scan history for the Vera app.
//
// There are no user accounts, so a viewer's history lives in their browser via
// localStorage. This module is an ES module used directly in the browser AND
// importable in Node for unit tests — the DOM-touching functions are guarded so
// importing it never requires a `document`/`window`.

const STORAGE_KEY = "tf_history_v1";
const MAX_ENTRIES = 200;

// --- Pure helpers (no DOM, no storage) -------------------------------------

// Same thresholds and language the product page uses for its score label.
export function computeBand(score) {
  if (score >= 70) return "good";
  if (score >= 40) return "mixed";
  return "poor";
}

// Dedupe by id, move the (re)viewed product to the top, cap the list length.
export function applyEntry(entries, entry, cap = MAX_ENTRIES) {
  const rest = entries.filter((e) => e.id !== entry.id);
  return [entry, ...rest].slice(0, cap);
}

export function countByBand(entries) {
  const counts = { good: 0, mixed: 0, poor: 0, total: entries.length };
  for (const e of entries) {
    if (e.band in counts) counts[e.band] += 1;
  }
  return counts;
}

// "just now" / "5 minutes ago" / "2 days ago". `now` is injectable for tests.
export function formatRelativeTime(ms, now = Date.now()) {
  const seconds = Math.max(0, Math.round((now - ms) / 1000));
  if (seconds < 45) return "just now";
  const units = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [name, secs] of units) {
    const value = Math.floor(seconds / secs);
    if (value >= 1) return `${value} ${name}${value === 1 ? "" : "s"} ago`;
  }
  return "just now";
}

// --- Storage (graceful when localStorage is unavailable) -------------------

// localStorage can throw or be absent (private mode, sandboxed iframe). Probe
// it once; if it fails, fall back to an in-memory store so the app never
// crashes — history just won't persist across page loads.
export function createSafeStorage(backing) {
  let store = backing;
  let available = true;
  try {
    if (!store) store = window.localStorage;
    const probe = "__tf_probe__";
    store.setItem(probe, "1");
    store.removeItem(probe);
  } catch (_e) {
    available = false;
    const mem = new Map();
    store = {
      getItem: (k) => (mem.has(k) ? mem.get(k) : null),
      setItem: (k, v) => mem.set(k, String(v)),
      removeItem: (k) => mem.delete(k),
    };
  }
  return { available, store };
}

let _safe = null;
function safe() {
  if (!_safe) _safe = createSafeStorage();
  return _safe;
}

export function storageAvailable() {
  return safe().available;
}

export function getHistory() {
  try {
    const raw = safe().store.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_e) {
    return [];
  }
}

function writeHistory(entries) {
  try {
    safe().store.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch (_e) {
    /* quota or serialization failure — drop silently */
  }
  return entries;
}

export function recordEntry(entry, now = Date.now()) {
  const full = { ...entry, viewedAt: entry.viewedAt ?? now };
  return writeHistory(applyEntry(getHistory(), full));
}

export function removeFromHistory(id) {
  return writeHistory(getHistory().filter((e) => e.id !== id));
}

export function clearHistory() {
  return writeHistory([]);
}

// --- DOM glue (guarded so the module imports cleanly in Node) --------------

const hasDom = typeof document !== "undefined";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// Read the hidden #history-record element on a product page and store the view.
export function recordView() {
  if (!hasDom) return;
  const el = document.getElementById("history-record");
  if (!el) return;
  const id = el.dataset.productId;
  if (!id) return;
  const score = parseInt(el.dataset.score, 10);
  recordEntry({
    id,
    name: el.dataset.name || id,
    brand: el.dataset.brand || "",
    image: el.dataset.image || "",
    score: Number.isFinite(score) ? score : 0,
    band: el.dataset.band || computeBand(Number.isFinite(score) ? score : 0),
  });
}

function thumbHtml(entry) {
  if (entry.image) {
    return `<img src="${escapeHtml(entry.image)}" alt="${escapeHtml(entry.name)}" loading="lazy">`;
  }
  return `<span class="history-thumb-placeholder" aria-hidden="true">🍽</span>`;
}

export function renderHistory() {
  if (!hasDom) return;
  const list = document.getElementById("history-list");
  const empty = document.getElementById("history-empty");
  const clearBtn = document.getElementById("history-clear");
  const unavailable = document.getElementById("history-unavailable");
  if (!list) return;

  const entries = getHistory();

  if (unavailable) unavailable.hidden = storageAvailable() || entries.length > 0;
  if (empty) empty.hidden = entries.length > 0;
  if (clearBtn) clearBtn.hidden = entries.length === 0;

  list.innerHTML = entries
    .map(
      (e) => `
    <li class="history-card">
      <a class="history-link" href="/product/${encodeURIComponent(e.id)}">
        <span class="history-thumb">${thumbHtml(e)}</span>
        <span class="history-info">
          <span class="history-name">${escapeHtml(e.name)}</span>
          ${e.brand ? `<span class="history-brand">${escapeHtml(e.brand)}</span>` : ""}
          <span class="history-time">${escapeHtml(formatRelativeTime(e.viewedAt))}</span>
        </span>
        <span class="history-score">
          <span class="history-dot history-dot--${escapeHtml(e.band)}" aria-hidden="true"></span>
          <span class="history-score-number">${escapeHtml(e.score)}</span>
        </span>
      </a>
      <button class="history-remove" type="button" data-remove="${escapeHtml(e.id)}"
              aria-label="Remove ${escapeHtml(e.name)} from history">×</button>
    </li>`
    )
    .join("");

  list.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", () => {
      removeFromHistory(btn.dataset.remove);
      renderHistory();
    });
  });

  if (clearBtn && !clearBtn.dataset.bound) {
    clearBtn.dataset.bound = "1";
    clearBtn.addEventListener("click", () => {
      if (confirm("Clear your entire scan history? This can't be undone.")) {
        clearHistory();
        renderHistory();
      }
    });
  }
}

export function renderOverview() {
  if (!hasDom) return;
  const chart = document.getElementById("overview-chart");
  const empty = document.getElementById("overview-empty");
  const unavailable = document.getElementById("overview-unavailable");
  if (!chart) return;

  const entries = getHistory();
  const counts = countByBand(entries);
  const max = Math.max(counts.good, counts.mixed, counts.poor, 1);

  if (unavailable) unavailable.hidden = storageAvailable() || entries.length > 0;
  if (empty) empty.hidden = entries.length > 0;
  chart.hidden = entries.length === 0;

  const rows = [
    ["good", "Good"],
    ["mixed", "Mixed"],
    ["poor", "Poor"],
  ];
  chart.innerHTML = `
    <p class="overview-total"><strong>${counts.total}</strong> product${counts.total === 1 ? "" : "s"} scanned</p>
    <ul class="overview-bars">
      ${rows
        .map(
          ([band, label]) => `
        <li class="overview-bar-item">
          <span class="overview-bar-label">${label}</span>
          <span class="overview-bar" aria-hidden="true">
            <span class="overview-bar-fill overview-bar-fill--${band}" style="width: ${(counts[band] / max) * 100}%"></span>
          </span>
          <span class="overview-bar-value">${counts[band]}</span>
        </li>`
        )
        .join("")}
    </ul>`;
}

// Auto-wire based on which page we're on.
if (hasDom) {
  document.addEventListener("DOMContentLoaded", () => {
    recordView();
    renderHistory();
    renderOverview();
  });
}
