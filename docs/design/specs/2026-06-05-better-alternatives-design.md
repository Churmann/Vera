# Better Alternatives — Design Spec

**Date:** 2026-06-05
**Status:** Approved
**Feature:** Yuka-style "better alternatives" recommendations on the product score page.

## Goal

On a product's score page, below the overall score, show 2–4 alternative products
from the **same food category** that score **strictly better** than the current
product. Each alternative shows its name, brand, thumbnail, score, and a coloured
score dot. Best-scoring first. If none are found, show a small
"No better alternatives found in this category" note.

Server-rendered, matching the existing design. Candidates are scored through the
**existing `FoodScoringEngine`** so their scores are directly comparable to the
current product's.

## Key constraint (verified)

search-a-licious (`search.openfoodfacts.org/search`) supports category filtering
(`q=categories_tags:"en:..."`) and returns `nutriscore_grade`, `nova_group`, and
`categories_tags` in hits — but **not** `additives_tags` (only a count,
`additives_n`). The additive scorer needs the real E-number list, so candidates
must be fetched as full products to be scored on the same path. Confirmed by live
probe on 2026-06-05.

## Decisions

1. **Scoring approach — fetch + score each (accurate).** One category search to get
   candidate codes, then concurrently `fetch_product` (existing cached method) and
   run the real `FoodScoringEngine` for each. Scores are identical-method and
   comparable. Costs extra OFF calls per page load, run in parallel (~1 round-trip
   of added latency), and cached.
2. **Category match — most-specific, broaden if sparse.** Use the most-specific
   `en:` category tag first; if fewer than 2 better alternatives are found, retry
   one level broader (cap ~3 levels). Cached fetches make re-scanning cheap.

## Architecture & data flow

In `product_score`, after the current product is scored:

1. Build an ordered list of `en:` category tags from the product's
   `categories_tags` (most-specific → broadest).
2. `search_category(tag)` → candidate codes, excluding the current product's code.
3. Concurrently `fetch_product` each candidate and `engine.score` it; compute its
   overall via the shared `weighted_overall(result)`.
4. Keep only candidates scoring **strictly higher** than the current product's
   overall; sort descending; take top 4.
5. **Broaden if sparse:** if fewer than 2 better at the most-specific level, retry
   one level broader (≤3 levels total). Track the best non-empty result across
   levels; return it if no level yields ≥2.
6. Render server-side. Empty result (none better, or lookup failed) → the empty
   note.

**Failure isolation:** the entire lookup is wrapped in try/except in the route;
any OFF error/timeout degrades to an empty list (→ empty note). The main score
page always renders.

## Components

### New
- **`app/alternatives.py`**
  - `Alternative` dataclass: `off_id, name, brand, image_url, score: int, band: str`
    (`band` ∈ `good|mixed|poor`).
  - `async def find_better_alternatives(off_client, engine, product, current_score,
    *, max_results=4, candidate_pool=12, max_levels=3) -> list[Alternative]`
  - `_ordered_category_tags(categories: list[str]) -> list[str]` — `en:` tags,
    most-specific first.
  - `_fetch_many(off_client, codes) -> list[NormalisedProduct]` —
    `asyncio.gather(return_exceptions=True)`, skipping failures.

### Changed
- **`app/off_client.py`**
  - Add `categories_tags` to `_PRODUCT_FIELDS`.
  - Add `async def search_category(self, tag, page_size=12) -> list[str]` returning
    candidate codes (query `categories_tags:"<tag>"`). Same error handling as
    `search`.
  - `_normalise` populates `categories`.
- **`app/models.py`**
  - `NormalisedProduct` gains `categories: list[str]`.
- **`app/scoring/food_engine.py`**
  - Add module-level `weighted_overall(result: ScoreResult) -> int` (the existing
    `_weighted_score` math, including `score_cap`). Single source of truth.
- **`app/main.py`**
  - `_weighted_score` refactored to call `weighted_overall`.
  - `product_score` awaits `find_better_alternatives` in try/except (→ `[]`) and
    passes `alternatives` to the template.

### Template & CSS
- **`templates/product.html`** — new `<section class="alternatives">` directly below
  the `overall-score` section. Each card links to `/product/{off_id}` with
  thumbnail (neutral placeholder if missing), name, brand, score number, and a
  coloured dot (good ≥70 / mixed ≥40 / poor, same thresholds as the score label).
  Empty → `<p class="alternatives-empty">`.
- **`static/css/style.css`** — alternatives grid/cards/score-dot styles using
  existing design tokens.

## Bounds

Candidate pool ~12 per level, max 4 shown, ≤3 broadening levels. Per-candidate
fetch failures are skipped, never aborting the batch. Re-scans across levels reuse
the client cache.

## Edge cases

- Product has no categories → empty list → note.
- Candidate missing nutriscore/nova → still scorable (engine handles `None`).
- Candidate with no image → neutral placeholder, still shown.
- Current product excluded by `off_id`; candidate codes de-duplicated.
- Alternative scores respect `score_cap` (via `weighted_overall`), same as the main
  product.

## Tests

- **Finder** (respx-mocked search + per-code product endpoints): only-better and
  sorted desc; capped at 4; excludes current product; broaden-if-sparse triggers
  when most-specific yields <2; none-better → empty; one failing candidate fetch
  doesn't break the batch.
- **OFF client**: `search_category` builds the right query and parses codes;
  `categories` parsed into `NormalisedProduct`.
- **Route**: product page renders the alternatives section (names + scores); renders
  the empty note when none are better.
