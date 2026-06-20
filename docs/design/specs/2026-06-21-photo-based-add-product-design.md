# Photo-based add-product flow

**Status:** Draft for review
**Date:** 2026-06-21
**Supersedes:** the text-entry portion of `2026-06-18-add-product-to-off-design.md`

## Problem

When a scanned barcode isn't in Open Food Facts, the user currently lands on a
form where they **type** the product name, brand, category, and quantity. Typed
data is unreliable (guessed names, missing nutrition) and defeats the point of an
honest scoring app. We want to replace typing with **guided photo capture**, like
Yuka: the user photographs the pack and Open Food Facts' Robotoff pipeline
extracts the data.

## Goals

- Replace manual text entry with guided capture of three photos: **front of
  pack, ingredients list, nutrition table**.
- Use plain file inputs with `capture` support so mobile opens the camera; no
  custom camera UI.
- Upload each photo to OFF as the correct image field (front / ingredients /
  nutrition) via the OFF SDK's image-upload API.
- Be honest about Robotoff's asynchronous processing: land the user on a real
  page with whatever data exists so far, under a clear pending banner — never a
  blank waiting screen — and **resolve to a definite end state**.
- Validate images server-side (type + size) with friendly errors.
- Reuse existing OFF auth, environment flag, and trust-store setup.
- Remove the old text path cleanly (code + tests), no dead code left behind.

## Non-goals

- No client-side camera UI, cropping, or rotation.
- No OCR / extraction in our app — that is Robotoff's job, server-side at OFF.
- No `product.update` text write. Uploading an image to a barcode creates the
  product in OFF automatically, so no separate text submission is needed.
- Setting `countries`/market on the new product is out of scope (possible later
  enhancement for region-aware alternatives).

## SDK verification (confirmed in installed `openfoodfacts==5.2.0`)

`api.product` is a `ProductResource`; the upload method lives on the **same
resource** the writer already uses for `update`:

```python
# openfoodfacts/api.py  (ProductResource)
def upload_image(self, code, image_path=None, image_data_base64=None, selected=None)
```

- **Upload + select in one call** via `selected`, e.g.
  `selected={"front": {"en": {}}}`. Valid field names: `front`, `ingredients`,
  `nutrition`, `packaging`. Structure: `field → 2-letter-lang → options-dict`.
- Accepts **base64 in memory** (`image_data_base64`) — no temp files. FastAPI
  `UploadFile` bytes → base64 → SDK.
- Requires **username + password** (we have it); forces **API v3**; POSTs JSON to
  `/api/v3/product/{code}/images`. Requires `code.isdigit()`.
- Synchronous (requests-based) → run in a threadpool, exactly like the existing
  `_write`. Inherits our auth, environment flag, and trust-store setup unchanged.

## User flow

1. Scanned barcode not found → `GET /product/{barcode}` not-found branch (or
   `GET /add?barcode=`) renders the photo-capture page, barcode prefilled.
2. The page states the requirement **up front** ("You'll need 3 clear photos:
   front, ingredients, nutrition table") with one-line guidance per shot, so the
   all-three rule is known before capture — not sprung at submit time.
3. User attaches three photos and submits.
4. Server validates (type + size + all-three-present), uploads each to OFF,
   makes one immediate re-fetch attempt, then redirects to
   `GET /product/{barcode}?submitted=1`.
5. The product page shows whatever data exists so far (front image and name
   often arrive quickly) under a pending banner, with a **"Check again"** button.
6. The pending state resolves automatically once enough data arrives, or to a
   final honest state once the freshness window passes (see "Pending lifecycle").

## Components and changes

### `app/config.py`
Add two configurable settings:

```python
off_max_image_bytes: int = 12 * 1024 * 1024   # 12 MB per photo
off_pending_window_seconds: int = 900          # 15 min: pending → final cutoff
off_image_lang: str = "en"                     # language code for selected images
```

Rationale for **12 MB**: modern phone photos — especially a zoomed nutrition-table
shot — routinely exceed 8 MB. With all three photos required, an 8 MB cap could
block a legitimate submission, which is the exact friction wall this feature
removes. Configurable via env.

### `app/image_validation.py` (new)
Keeps validation out of `main.py` and independently testable.

```python
ALLOWED = {"image/jpeg", "image/png", "image/webp"}

def sniff_image_type(data: bytes) -> str | None:
    """Return 'jpeg'|'png'|'webp' from the leading magic bytes, else None.
    Filename, extension, and declared Content-Type are ignored — only the bytes
    decide."""

def validate_image(data: bytes, *, max_bytes: int) -> str | None:
    """Return a friendly error string, or None if the image is acceptable.
    Checks non-empty, size <= max_bytes, and a recognised magic-byte signature."""
```

Magic-byte signatures:
- JPEG: `FF D8 FF`
- PNG: `89 50 4E 47 0D 0A 1A 0A`
- WEBP: bytes 0–3 `RIFF` and bytes 8–11 `WEBP`

Because the sniff reads actual bytes, a non-image renamed to `.jpg` (e.g. a PDF,
whose header is `%PDF` = `25 50 44 46`) matches no signature and is rejected —
even if the client sends `Content-Type: image/jpeg`. This is covered by a
dedicated test (see Testing).

### `app/off_writer.py`
**Remove** `add_product` and `_write` (the text `product.update` path).
**Add**:

```python
_IMAGE_FIELDS = ("front", "ingredients", "nutrition")

async def add_product_photos(self, *, barcode: str, images: dict[str, bytes]) -> None:
    """Upload front/ingredients/nutrition photos to OFF for `barcode`.
    `images` maps field name -> raw bytes. Each is base64-encoded and uploaded
    via product.upload_image(..., selected={field: {lang: {}}}) in a threadpool.
    Raises OFFError('no_credentials') if creds are unset, OFFError('write_failed')
    on a request error or non-success SDK response."""
```

- Credentials checked first (mirrors the old method) → `no_credentials`.
- Language from `settings.off_image_lang`.
- Each upload runs via `asyncio.to_thread`; `requests.RequestException` and any
  non-OK response map to `OFFError(..., "write_failed")`.
- Reuses the existing `_build_api` / `api_factory` (already v3-forced internally,
  authenticated, environment-aware, trust-store-routed). `api_factory` stays
  injectable for tests.

### `app/main.py`

**`POST /add` (rewritten).** Accepts `barcode` (form) + three `UploadFile`s:
`front_photo`, `ingredients_photo`, `nutrition_photo`.

Validation order (re-render `add.html` with a specific message + preserved
barcode on any failure; never attempt the upload until all pass):
1. Barcode via `_clean_barcode` → "Enter a valid barcode — 8 to 14 digits."
2. Each photo **present** → e.g. "Nutrition photo needed." (one message per
   missing field).
3. Each photo read into memory and passed through `validate_image` → friendly
   per-field type/size error (e.g. "The ingredients photo must be a JPG, PNG, or
   WEBP image." / "The nutrition photo is too large (max 12 MB).").

On success:
- `await off_writer.add_product_photos(barcode=clean, images={...})`; map
  `OFFError` kinds to the existing friendly messages (`no_credentials` → 503
  "Submitting products isn't configured…"; otherwise → 502 "Couldn't save to
  Open Food Facts…"), re-rendering `add.html`.
- `await _refetch_after_write(off_client, clean, base_backoff=...)` — one
  immediate bounded attempt (reused as-is).
- `return RedirectResponse(f"/product/{clean}?submitted=1", status_code=303)`
  regardless of whether the immediate re-fetch found it — the product page owns
  the pending/partial presentation.

**`GET /add`.** Unchanged route; now renders the photo-capture `add.html`
(barcode prefilled from `?barcode=`). Still the target of the empty-search
"Add product" affordance; when reached without a barcode, the barcode field is
empty and editable.

**`GET /product/{off_id}` (pending-aware).** Add `submitted: bool = False` query
param. New helper:

```python
def _is_awaiting_extraction(p: NormalisedProduct) -> bool:
    """True when the product lacks enough to score: no nutriscore_grade AND no
    nutriments."""
```

Render logic:
- Not-found **and** `submitted` → render a minimal **pending shell** (barcode +
  pending banner + "Check again") instead of the photo page. This avoids the
  loop where a freshly-submitted product that OFF hasn't materialised yet bounces
  the user back to capture. Not-found and **not** submitted → unchanged
  (photo-capture page, as today's not-found behaviour).
- Found and `_is_awaiting_extraction` → **suppress** the numeric score and
  alternatives; render the product shell (front image, name, any nutrient bars
  that exist) with the pending banner (see lifecycle for banner-vs-final).
- Found and complete → render the score page exactly as today (no banner).

### Pending lifecycle (definite end state)

The banner must never promise "still reading" forever. Resolution is **stateless
and time-bounded**, driven by OFF's `created_t` (added to the fetch — see
`off_client.py`):

Let `age = now - created_t` and `window = settings.off_pending_window_seconds`.

| Condition | Page state |
|---|---|
| Enough data to score (`not _is_awaiting_extraction`) | **Final.** Normal score page, no banner. (Robotoff arrival resolves pending automatically — including partial extraction that yields a Nutri-Score or nutriments.) |
| Awaiting extraction **and** `age < window` | **Pending.** Banner: "We're still reading the label — the score will fill in shortly." + "Check again" button → `/product/{barcode}` (re-fetches; the same rules re-evaluate). |
| Awaiting extraction **and** `age >= window` | **Final, honest.** No score, no "Check again". Calm message: "We couldn't read enough from the photos to score this yet. The product is now in Open Food Facts and its details may be completed over time." + link to the OFF product page. |

This handles every Robotoff outcome: full extraction and partial-but-sufficient
extraction both flip to the scored final state; a stall or insufficient
extraction lands in the time-bounded honest final state. An **old, incomplete**
product (added long ago by someone else) is `age >= window` from the start, so it
shows the honest final state, never a misleading "still reading."

`submitted=1` only warms the first-redirect copy ("Thanks — photos received.");
the lifecycle rules above are the authority on subsequent loads and "Check
again" clicks, so the behaviour is correct even if the user revisits the URL
later.

### `app/off_client.py`
Add `created_t` to `_PRODUCT_FIELDS` and parse it in `_normalise` into a new
`NormalisedProduct.created_t: int | None`. No other read-path changes.

### `app/models.py`
Add `created_t: int | None = None` to `NormalisedProduct`.

### `templates/add.html` (rewritten)
- Keeps `{% extends "base.html" %}`, the `.search-hero.add-product` section, the
  back-link, heading, and tagline (updated copy).
- **Up-front requirements block**: "You'll need 3 clear photos" + the three
  shots listed, so the all-three rule is visible before capture.
- `<form action="/add" method="post" enctype="multipart/form-data">` with:
  - Barcode field (prefilled when known; editable; `required`).
  - Three labelled file inputs — `front_photo`, `ingredients_photo`,
    `nutrition_photo` — each
    `type="file" accept="image/jpeg,image/png,image/webp" capture="environment"`,
    with a one-line guidance caption per shot (e.g. "Fill the frame, avoid
    glare; make sure the text is readable").
  - Submit button: "Upload & score".
- Preserves the barcode and shows per-field error / notice text on re-render
  (reusing the existing `form-error` / `form-notice` patterns).
- **Removed:** the `name`, `brand`, `category`, `quantity` text inputs.

### `templates/product.html`
- Add a **pending banner** partial at the top of the content, shown per the
  lifecycle table.
- Add the **"Check again"** button (a plain link to `/product/{barcode}`) in the
  pending state.
- Guard the score/alternatives/factors blocks so they render only when **not**
  awaiting extraction; otherwise show the partial shell (front image, name, any
  nutrient bars) plus the banner, or the honest final message past the window.

### `static/css/style.css`
- Styles for the requirements block, file inputs, and per-shot guidance captions,
  reusing existing design tokens/spacing.
- Pending banner + "Check again" button styling, consistent with existing
  `form-notice` / button styles.

## Files changed

| File | Change |
|---|---|
| `app/config.py` | Add `off_max_image_bytes` (12 MB), `off_pending_window_seconds` (900), `off_image_lang` ("en"). |
| `app/image_validation.py` | **New.** `sniff_image_type`, `validate_image`. |
| `app/off_writer.py` | Remove text `add_product`/`_write`; add `add_product_photos`. |
| `app/off_client.py` | Add `created_t` to product fields + `_normalise`. |
| `app/models.py` | Add `created_t` to `NormalisedProduct`. |
| `app/main.py` | Rewrite `POST /add` (file upload + validation); pending-aware `GET /product`; add `_is_awaiting_extraction`. |
| `templates/add.html` | Rewrite to guided photo capture; remove text fields. |
| `templates/product.html` | Pending banner + "Check again"; guard score blocks. |
| `static/css/style.css` | Styles for capture UI + pending banner. |
| `tests/test_routes.py` | Replace text-add tests with photo-flow tests. |
| `tests/test_off_writer.py` | Replace text-update tests with upload tests. |

No `requirements.txt` change — `python-multipart` is already present; byte
sniffing avoids needing Pillow.

## What is removed

- `templates/add.html`: `name`, `brand`, `category`, `quantity` inputs.
- `app/main.py`: text handling in `POST /add` (`Form` name/brand/category/
  quantity, name-required validation, text `form_ctx` echo).
- `app/off_writer.py`: `add_product` and `_write` (text `product.update`).
- `tests/test_routes.py`: `test_add_page_renders_form` (text version),
  `test_add_submit_requires_name`, `test_add_submit_success_redirects_to_product`,
  `test_add_submit_missing_credentials_shows_friendly_message`,
  `test_add_submit_write_failure_shows_friendly_message`,
  `test_add_submit_trims_whitespace_from_barcode_before_validating`,
  `test_add_submit_not_yet_queryable_shows_refresh_notice`. The barcode-validation
  intent is preserved in a new photo-flow test.
- `tests/test_off_writer.py`: all four current text-update tests.

## Error handling

- **Validation failures** (barcode, missing photo, wrong type, too large) →
  re-render `add.html`, HTTP 400, specific message, barcode preserved, upload
  never attempted.
- **`no_credentials`** → 503, "Submitting products isn't configured on this
  server yet."
- **Upload failure** (`write_failed`) → 502, "Couldn't save to Open Food Facts —
  please try again," barcode preserved.
- **Post-upload not yet queryable** → redirect to the product page's pending
  shell, never an error.
- **Renamed non-image** → rejected by the magic-byte sniff with the type error.

## Testing

`app/image_validation.py` (unit):
- Accepts minimal valid JPEG / PNG / WEBP byte headers.
- Rejects empty input.
- Rejects oversized input (size > `max_bytes`) with the size message.
- **Rejects a PDF (`%PDF…`) renamed `.jpg`** → returns the type error (the
  filename and a spoofed `image/jpeg` content-type do not matter; only bytes do).

`app/off_writer.py` (unit, fake `ProductResource` capturing `upload_image`):
- Uploads all three fields with the right `selected={field: {lang: {}}}` and
  base64 of the bytes.
- Missing credentials → `OFFError('no_credentials')`, no upload attempted.
- A `requests` error / non-OK response → `OFFError('write_failed')`.

`app/main.py` routes (TestClient + stub writer / `respx`):
- `GET /add` renders three file inputs + barcode field; no text fields.
- `GET /add?barcode=` prefills the barcode.
- `POST /add` with all three valid images → 303 to
  `/product/{barcode}?submitted=1`; writer received three byte blobs.
- `POST /add` missing the nutrition photo → 400, "Nutrition photo needed,"
  barcode preserved, writer not called.
- `POST /add` with a renamed-PDF front photo → 400, type error, writer not
  called. (Route-level guard, complementing the unit test.)
- `POST /add` invalid barcode → 400, range message, writer not called.
- `POST /add` no credentials / write failure → 503 / 502 friendly messages.
- `GET /product/{barcode}?submitted=1` when OFF still 404s → pending shell with
  "Check again," not the capture page.
- `GET /product/{barcode}` for an incomplete **fresh** product (recent
  `created_t`) → pending banner, no score.
- `GET /product/{barcode}` for an incomplete **old** product (`created_t` beyond
  the window) → honest final message, no "Check again," no score.
- `GET /product/{barcode}` for a complete product → normal score page, no banner
  (regression guard that existing behaviour is unchanged).

## Open defaults (chosen, configurable)

- Max image size: **12 MB** per photo (`off_max_image_bytes`).
- Pending window: **15 min** (`off_pending_window_seconds`).
- Image language: **`en`** (`off_image_lang`).
