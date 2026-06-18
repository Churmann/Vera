# Add missing products to Open Food Facts

**Date:** 2026-06-18
**Status:** Implemented
**Component:** Vera — search / barcode "not found" path, OFF write client

## Problem

When a barcode lookup or name search finds no product, Vera is a dead end:

- `GET /product/{off_id}` raises `OFFError(kind="not_found")` and renders
  `error.html` with a 404 ("Product not found on Open Food Facts").
- `GET /search` with no hits renders `results.html`'s "No products found…
  try a different search term" branch.

Open Food Facts is crowd-sourced and incomplete, so this happens for real
products. Today the only way to grow Vera's catalogue is a bigger/paid database.

## Goal

Let users add a missing product **directly into Open Food Facts** from the
not-found page. The product becomes a permanent OFF record, so Vera's coverage
grows for free. After a successful write, re-fetch that barcode, score it with
the existing engine, and show the normal Vera product page immediately.

This is the planned `TODO.md` enhancement: "Let users submit data for products
missing from Open Food Facts… the way Yuka handles coverage gaps."

## Non-goals / guardrails (v1)

- **No live camera barcode scanning.** Manual barcode entry only. Camera
  scanning is a separate later task (already deferred on the `/scan` page).
- **No photo upload.** OFF image upload is a separate multipart API call, not
  `api.product.update`. Deferred to v2.
- **No editing existing products.** Add-only.
- **Username/password auth only.** No OAuth.
- **No new framework or restructuring.** Match existing route naming, the app
  factory + `app.state` pattern, Jinja2 templates that extend `base.html`, and
  the hand-written CSS. No build step.
- Scoring, weights, the integrity cap, search, and alternatives logic are
  untouched.

## Key facts about the OFF write API

- Use the official `openfoodfacts` Python SDK (not hand-rolled HTTP).
- Writes require authentication. `user_id` is the OFF **username**, not the
  email. A **User-Agent** string is mandatory on the API client.
- Build and test against the **staging** server (`world.openfoodfacts.net`)
  first, with a flag to switch to **production** (`world.openfoodfacts.org`)
  later. **Staging and production are separate accounts** with separate
  credentials.
- The SDK is **synchronous** (requests-based); Vera's routes are async, so the
  write must run in a threadpool to avoid blocking the event loop.

## Architecture

### 1. Configuration — `app/config.py`, `.env.example`, `README.md`

Add to `Settings`:

| Setting | Default | Purpose |
|---|---|---|
| `off_environment` | `"production"` | `"staging"` → `world.openfoodfacts.net`, `"production"` → `world.openfoodfacts.org`. Drives **both** the SDK write target and `off_client`'s read host. |
| `off_username` | `None` | OFF username (NOT email). Secret, env-only. |
| `off_password` | `None` | OFF password. Secret, env-only. |

Credentials are optional so the app still boots for read-only browsing; the add
route surfaces a clear error if they are unset.

**Default is `production` (safe default), opt in to `staging`.** Because the flag
also drives the read host, defaulting to production keeps the live app (and the
existing test suite, which mocks `world.openfoodfacts.org`) reading real data. To
build and test writes against staging first, set `OFF_ENVIRONMENT=staging` in the
local `.env` (this is what `.env.example` ships). Once writes are validated, the
production deploy needs no change (or sets `OFF_ENVIRONMENT=production` explicitly
on Render). Staging reads (`world.openfoodfacts.net`) sit behind an HTTP
Basic-auth gate (`off:off`); the OFF SDK handles this automatically for writes,
and `off_client` must send the same Basic auth on staging reads (the post-write
re-fetch).

`.env.example` gains `OFF_ENVIRONMENT`, `OFF_USERNAME`, `OFF_PASSWORD`, with a
comment that the username is **not** the email and that staging/production use
separate accounts. The README "Configuration" section documents these and notes
they must **also** be set in **Render's environment**. `.env` stays gitignored;
only `.env.example` is committed. Credentials are never hardcoded or committed.

### 2. Environment-aware read host — `app/off_client.py`

`_PRODUCT_URL` and the `raw_off_url` host are currently hardcoded to
`world.openfoodfacts.org`. Derive the product host from
`settings.off_environment` so a product just written to **staging** can be
re-fetched and scored.

In staging mode the read host is `world.openfoodfacts.net`, which is behind an
HTTP Basic-auth gate (`off:off`). The httpx client must send this Basic auth on
product fetches in staging mode (per-request `auth=("off", "off")`, not on the
shared client, so production search-a-licious requests are unaffected).

Name search stays on production search-a-licious (`search.openfoodfacts.org`) —
staging search isn't reliable, and only the post-write re-fetch (a direct
barcode fetch on the v2 product API) needs the staging host.

### 3. New module — `app/off_writer.py`

Mirrors `off_client.py`'s separation of concerns.

- Wraps the SDK `API` object: `username`, `password`, mandatory `user_agent`
  (reuses `settings.off_user_agent`), and the environment from the flag.
- `add_product(barcode, name, brand, category, quantity)` builds the update body
  and calls `api.product.update(...)`. The blocking call runs via
  `asyncio.to_thread` / `run_in_threadpool`.
- Raises a typed error (reusing/mirroring `OFFError`) on **missing credentials**
  or **write failure**, so routes render a friendly message without losing the
  user's typed input.
- Constructed in `lifespan` and stored on `app.state.off_writer`, exactly like
  `off_client`.

SDK shape (verified against `openfoodfacts` 5.2.0):
`API(user_agent=..., username=..., password=..., environment=Environment.net|org)`
then `api.product.update(body)`, where `body` must include `"code"`. The SDK
auto-injects `user_id`/`password`, handles staging Basic auth, and calls
`raise_for_status()`, so write failures raise `requests.RequestException` (mapped
to `OFFError(kind="write_failed")`). Missing credentials →
`OFFError(kind="no_credentials")`.

### 4. Routes — `app/main.py`

- **`GET /add`** — renders `add.html`; accepts `?barcode=` to prefill.
- **`GET /product/{off_id}` not-found branch** — instead of the dead-end
  `error.html`, render the add form with the barcode prefilled.
- **Empty search** — `results.html` gains an "Add a product" link to `/add`
  (barcode blank; the user types it).
- **`POST /add`** — validate (see below) → `off_writer.add_product(...)` →
  post-write re-fetch (see "Post-write read delay") → **redirect to
  `/product/{barcode}`**, which already fetches (now from the configured
  environment), scores, and renders. On validation / write / credential failure,
  re-render `add.html` with the entered values and an error message.

### 5. Post-write read delay (addition 1)

After a successful write, OFF can take a moment before the product is queryable,
so an immediate re-fetch may hit "not found" for a product just added.

**Chosen approach: bounded retry-with-backoff on the post-write fetch, scoped to
the POST `/add` handler.** After a successful write, poll `off_client.fetch_product`,
catching `OFFError(kind="not_found")`, with a concrete budget:

- **3 retries** after the initial fetch.
- **0.5s base exponential backoff**, reusing the existing `off_retry_backoff`
  pattern in `off_client` (`off_retry_backoff * (2 ** attempt)` → sleeps of
  0.5s, 1.0s, 2.0s = 3.5s total backoff).
- **Hard total-wait ceiling of ~4 seconds.** The user never waits longer than
  this ceiling before seeing either the scored page or the "refresh shortly"
  confirmation, regardless of fetch latency — the loop stops as soon as the
  ceiling is reached even if retries remain.

On success, redirect to `/product/{barcode}` — the fetch has warmed
`off_client`'s TTL cache, so the product page scores instantly. If the product
is still not queryable when the retry budget (or the ~4s ceiling) is exhausted,
show a friendly confirmation ("Added to Open Food Facts — it may take a moment
to appear; refresh shortly") rather than an error, because **the write did
succeed**.

**Why not render the score inline from submitted data?** The submitted fields
(barcode, name, brand, category, quantity) carry no nutriments, Nutri-Score, or
NOVA group, so an inline score would duplicate the normalise/score path and
produce a *different, thinner* result than the canonical OFF record. Retrying the
real fetch keeps a single scoring/rendering path and reuses the existing
fetch + score + alternatives route untouched.

**Scope note:** the retry lives in the POST `/add` flow only. Normal browsing's
not-found behaviour stays instant — `fetch_product` is not made to retry on 404
generally, since fast not-found → add-form is the whole point of this feature.

### 6. Validation — `POST /add`

- **Barcode (addition 2):** trim surrounding whitespace (including trailing
  spaces and newlines from pasting) **first**, then validate the result is
  **8–14 digits** (EAN-8 / UPC-A / EAN-13 / GTIN-14, matching `scan.js`'s
  `normalizeBarcode`). Reject anything else with a clear message.
- **Product name:** required (OFF needs a code; a name is the minimum useful
  content). Trimmed.
- **Brand, category, quantity:** optional; trimmed; sent only when non-empty.

Invalid input re-renders `add.html` with the entered values and a field-level
error, never a dead end.

### 7. Template — `templates/add.html`

Extends `base.html`. Matches the existing `search-hero` / `search-form` /
`form-error` visual style. Fields: barcode, product name, brand, category,
quantity. No photo input (deferred). Reuses existing CSS classes; only minimal
additions to `static/css/style.css` if needed.

### 8. Dependencies — `requirements.txt`

Add `openfoodfacts` (the official SDK), pinned to the current version.

## Data flow

```
not found (search empty OR /product 404)
        │
        ▼
  GET /add  ──renders──►  add.html (barcode prefilled if from /product)
        │
   user submits
        ▼
  POST /add
        │ trim + validate barcode (8–14 digits), name required
        ▼
  off_writer.add_product(...)  ──SDK api.product.update via threadpool──►  OFF (staging|prod)
        │ success
        ▼
  re-fetch barcode with bounded retry/backoff (3 retries, 0.5s base, ~4s ceiling)
        │
        ├─ queryable ──► redirect /product/{barcode} ──► fetch + score + render (cache warm)
        └─ not yet    ──► friendly "added, refresh shortly" confirmation
```

## Error handling

| Condition | Behaviour |
|---|---|
| Credentials unset | `add_product` raises typed error → `add.html` re-rendered with a clear "submission isn't configured" message; typed values preserved. |
| Invalid / non-8–14-digit barcode | `add.html` re-rendered with field error; values preserved. |
| SDK write failure (auth, network, OFF error) | `add.html` re-rendered with a friendly error; values preserved. |
| Write OK, product not yet queryable after retries | Friendly "added — refresh shortly" confirmation (not an error). |
| Write OK, product queryable | Redirect to `/product/{barcode}`; normal score page (low confidence expected, since no Nutri-Score/NOVA yet). |

## Testing — `tests/test_routes.py`, `tests/test_off_writer.py` (new)

- `GET /product/{unknown}` now renders the add form with the barcode prefilled
  instead of the 404 error page — **intentional behaviour change**; update
  `test_product_not_found_returns_404` accordingly.
- Empty search renders the "Add a product" link.
- `GET /add` renders the form; prefills `?barcode=`.
- `POST /add` happy path: writer faked on `app.state.off_writer`, staging product
  URL mocked via `respx`, asserts redirect to `/product/{barcode}` and a scored
  page.
- `POST /add` failure paths: missing credentials, write error, invalid/whitespace
  barcode (asserts trim-then-validate), name missing.
- Post-write retry: first fetch 404 then 200 (retry succeeds → redirect);
  persistent 404 → friendly confirmation after the bounded budget (3 retries /
  ~4s ceiling), asserting the loop stops at the budget rather than waiting longer.
- `off_writer` unit tests with a fake/injected SDK client (the SDK is
  requests-based, so fake at the writer boundary rather than via `respx`):
  body construction, optional fields omitted when empty, missing-credential error.

## Files touched

- `app/config.py` — new settings
- `app/off_client.py` — environment-aware read host
- `app/off_writer.py` — **new**, OFF SDK write wrapper
- `app/main.py` — `GET /add`, `POST /add`, not-found branch, wiring on `app.state`
- `templates/add.html` — **new**
- `templates/results.html` — "Add a product" link
- `static/css/style.css` — minimal additions if needed
- `requirements.txt` — add `openfoodfacts`
- `.env.example` — new vars
- `README.md` — document config + Render env vars
- `tests/test_routes.py` — add-flow + updated not-found test
- `tests/test_off_writer.py` — **new**
