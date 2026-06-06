# History & Overview — Design

Date: 2026-06-06

## Goal

Add two Yuka-like features to the Vera app, in our own calm muted style:

1. **History** — automatically remember products the user has viewed, and a
   `/history` page listing them (thumbnail, name, brand, score, colour dot,
   "viewed X ago"), most recent first, each linking back to its product page.
2. **Overview** — a `/overview` page summarising scan history: a breakdown by
   grade (Good / Mixed / Poor) as horizontal bars plus counts and a total.

There are no user accounts, so history lives in the browser via `localStorage`.

## Constraints

- Keep everything **server-rendered** except the history data itself, which is
  client-side only.
- Match the existing calm identity (muted sage/amber/red palette, soft shadows,
  rounded cards). Not a Yuka clone.
- `localStorage` may be unavailable (private mode, sandboxed iframe). Handle it
  **gracefully** — never crash; degrade to non-persistent behaviour with a note.
- An existing test asserts the product page contains neither the string
  `score-data` nor `scorer.js`. The new recorder must avoid those names.

## Architecture

Server-rendered shells + client-side data:

- New routes `/history` and `/overview` render normal Jinja pages (nav,
  headings, empty-state markup, controls). Only the list/chart content is
  rendered client-side by `static/js/history.js` reading `localStorage`.
- The product page records a view on load via the same module.

### Recording (product page)

`product.html` includes one hidden element carrying server-rendered values as
data-attributes:

```
<div id="history-record"
     data-product-id="..." data-name="..." data-brand="..."
     data-image="..." data-score="73" data-band="good" hidden></div>
```

`band` is the same Good/Mixed/Poor the page already computes for the score
label. Element id `history-record` and script `history.js` deliberately avoid
the forbidden `score-data` / `scorer.js` strings. On load `history.js` reads
these attributes and records the view.

### Data model — `localStorage`

- Key: `tf_history_v1`.
- Value: JSON array, newest-first. Each entry:
  `{ id, name, brand, image, score, band, viewedAt }`
  (`id` = OFF id; `score` int; `band` one of `good|mixed|poor`;
  `viewedAt` = epoch ms).
- On record: remove any existing entry with the same `id`, unshift the new one
  (dedupe + move-to-top), cap the array at **200** entries.

### `static/js/history.js` (ES module)

- `safeStorage`: feature-tests `localStorage` in a try/catch (probe set/get/
  remove). If unavailable, falls back to an in-memory object so nothing
  crashes; `safeStorage.available` is `false` in that case.
- Pure, environment-free helpers (exported for tests):
  - `computeBand(score)` → `good` (≥70) / `mixed` (40–69) / `poor` (<40).
  - `formatRelativeTime(ms, now)` → "just now", "5 minutes ago", "2 days ago"…
  - `applyEntry(entries, entry, cap)` → dedupe by id, move-to-top, cap.
  - `countByBand(entries)` → `{ good, mixed, poor, total }`.
- DOM functions (guarded with `typeof document !== 'undefined'`):
  `recordView()`, `renderHistory()`, `renderOverview()`,
  plus `getHistory()`, `removeFromHistory(id)`, `clearHistory()`.
- Each page includes the module and calls the relevant entry point.

## Pages

### /history

- Server: nav, `<h1>History</h1>`, a "Clear all history" button (shown only
  when entries exist), an empty-state `<p>`, and an empty `<ul id="history-list">`.
- Client rows: thumbnail · name · brand · score number + colour dot ·
  "viewed X ago" · remove (×) button. The row links to `/product/{id}`.
- "Clear all history" → `confirm()` → `clearHistory()` → re-render.
- Remove (×) → `removeFromHistory(id)` → re-render.
- If storage unavailable: show a gentle note that history isn't available here.

### /overview

- Server: nav, `<h1>Overview</h1>`, empty-state, and a container for the chart.
- Client: three horizontal bars (Good/Mixed/Poor) reusing the existing
  `weight-bar` style with the muted band colours, each with its count, plus a
  total "products scanned" figure.
- Empty / unavailable states mirror the history page.

## Navigation

Add `.site-nav` to `base.html` header — Search (`/`), History (`/history`),
Overview (`/overview`) — with active-page styling, in the existing palette.
Active page is determined server-side from the request path.

## Colour bands

Reuse existing thresholds and palette: Good ≥70 (`--color-good`),
Mixed 40–69 (`--color-moderate`), Poor <40 (`--color-poor`).

## Testing

- **Python** (`tests/test_routes.py`): `/history` and `/overview` return 200
  with expected scaffolding (nav links, headings, empty-state text, `history.js`
  include); nav present across pages; product page emits the `history-record`
  element without reintroducing `score-data` / `scorer.js`.
- **JS** (`tests/js/history.test.mjs`, run via built-in `node --test`, no new
  deps): unit-test the pure helpers — `computeBand` thresholds, `applyEntry`
  dedupe/cap/move-to-top, `countByBand`, `formatRelativeTime`.

## Out of scope (YAGNI)

- Server-side persistence / accounts.
- Export/import, search/filter within history, per-day grouping.
- Charting libraries — bars are pure CSS.
