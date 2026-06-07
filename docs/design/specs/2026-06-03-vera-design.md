# Vera Design Spec
**Date:** 2026-06-03
**Status:** Approved

> **Note — original spec; implementation has evolved.** This is the original v1 design and is kept for historical context. Several deliberate design decisions were made after this was written:
> - **Fixed, transparent weights** instead of user-adjustable weight sliders — adjustable weights let users game the score, which undermines the integrity of a single trustworthy verdict.
> - **Barcode scanning added** — the camera scanner removes the friction of typing product names (this spec describes name search only).
> - **Better-alternatives recommendations, scan history, and an overview page added** — features that extend the original scope.
>
> For the current feature set, see the [README](../../../README.md).

## Overview

A web app that scores the healthiness and safety of food products, designed as a transparent, evidence-based alternative to Yuka. Every design decision fixes a documented Yuka complaint: no opaque single verdict, visible weights, per-ingredient evidence with sources, honest uncertainty, and positives shown alongside flags.

v1 is food-only. The scoring engine is a pluggable Python Protocol so a cosmetics module can be added later without touching the app shell.

**Stack:** Python 3.12 / FastAPI / Jinja2 / vanilla JS / Docker  
**Data:** Open Food Facts API (search by product name; no barcode scanning in v1)  
**Accounts:** None in v1

---

## Core Principles (each fixing a Yuka flaw)

1. Never lead with a single number — show the per-dimension breakdown and the positives too.
2. Make weighting explicit and visible — user can adjust weights live.
3. Every flagged ingredient shows evidence, dose/context, and a source link.
4. Show a data-confidence indicator and link to the raw Open Food Facts source.
5. Acknowledge uncertainty instead of false precision.

---

## Architecture

```
Browser
  │  search query
  ▼
FastAPI app (single process)
  ├── GET /             → search page (Jinja2)
  ├── GET /search       → results list (Jinja2)
  ├── GET /product/{id} → score page (Jinja2, score payload embedded)
  └── GET /healthz      → health check

FastAPI app (internal)
  ├── OFFClient         async HTTP wrapper for Open Food Facts
  ├── AdditiveDB        hybrid taxonomy + curated YAML, loaded at startup
  └── ScoringEngine (Protocol)
        └── FoodScoringEngine
              ├── NutritionScorer
              ├── AdditiveScorer
              └── NovaScorer
```

### Score payload delivery

The `/product/{off_id}` route serialises the full `ScoreResult` into a `<script type="application/json" id="score-data">` tag in the rendered HTML. The server also renders the initial weighted total using default weights, so the page is fully meaningful without JS (progressive enhancement). JS reads the embedded payload on load and wires the weight sliders for live recalculation — no second request needed.

---

## Scoring Engine

### Protocol

```python
class ScoringEngine(Protocol):
    def score(self, product: NormalisedProduct) -> ScoreResult: ...
```

Adding cosmetics later means writing `CosmeticsScoringEngine` that satisfies this protocol. No changes to routes, templates, or JS.

### Data models

**`NormalisedProduct`** (dataclass)
- `off_id: str`
- `name: str`
- `brand: str | None`
- `nutriscore_grade: str | None`  (A–E)
- `nova_group: int | None`  (1–4)
- `additives: list[str]`  (E-numbers)
- `ingredients_text: str | None`
- `image_url: str | None`
- `raw_off_url: str`

**`ScoreResult`**
- `dimensions: list[DimensionScore]`
- `confidence: ConfidenceLevel`  (high / medium / low)
- `confidence_notes: list[str]`
- `off_url: str`

**`DimensionScore`**
- `id: str`
- `label: str`
- `score: int`  (0–100)
- `input_label: str`  (e.g. `"Nutri-Score C"`, `"NOVA group 4"`)
- `input_value: int`  (e.g. `60`, `0`)
- `weight_default: float`
- `summary: str`
- `positives: list[str]`
- `flags: list[EvidenceCard]`

**`EvidenceCard`** (additives)
- `name: str`
- `e_number: str`
- `risk_level: RiskLevel`  (low / moderate / high / unknown)
- `evidence_summary: str`
- `dose_context: str`
- `source_url: str | None`

**`ConfidenceLevel`**: `high` (Nutri-Score grade + NOVA group both present), `medium` (one of the two missing), `low` (both missing). Additives do not affect confidence — an empty additives list means the product has no additives, not that data is missing; `nutriscore_grade is None` and `nova_group is None` are the only signals of incomplete data.

### Scoring tables (`scoring/tables.py`)

A single file of plain dicts — no logic. Documented as deliberate v1 simplifications, easy to find and adjust.

```python
# Deliberate v1 simplification — refine in a later iteration
NUTRISCORE_TO_SCORE = {"A": 100, "B": 80, "C": 60, "D": 40, "E": 20}
NOVA_TO_SCORE = {1: 100, 2: 75, 3: 40, 4: 0}
```

### Default weights

| Dimension | Default weight |
|-----------|---------------|
| Nutrition | 50% |
| Additives | 30% |
| Processing (NOVA) | 20% |

Weights are shown to the user and adjustable via sliders. They always sum to 100%; adjusting one redistributes the remainder proportionally.

---

## Data Layer

### Open Food Facts client (`app/off_client.py`)

- Async HTTP client (httpx) wrapping the OFF Search API and product API.
- Search by name returns up to 10 matches (name, brand, thumbnail, OFF id).
- Product fetch returns `NormalisedProduct`; missing fields map to `None`.
- **User-Agent:** descriptive, configurable via `OFF_USER_AGENT` env var (e.g. `"VeraApp/1.0 (contact@example.com)"`). Required by OFF API policy.
- **Timeout:** configurable via `OFF_REQUEST_TIMEOUT` env var, default 8s.
- **Error handling:** timeouts and HTTP 429 map to a typed `OFFError`; the route layer surfaces these as a user-facing "couldn't reach Open Food Facts — try again" message (renders `error.html`), never a 500.
- **In-process cache:** TTL-based (default 5 min), keyed on OFF id. Avoids hammering OFF on repeated views.

### Additives DB (`app/additive_db.py`)

Loaded once at startup. Two sources merged at startup:

1. `data/additives_off_taxonomy.json` — downloaded from OFF additives taxonomy at build time. Provides E-number, canonical name, `risk_level` for ~300+ additives.
2. `data/additives_curated.yaml` — hand-authored, ~20 entries. Adds `evidence_summary`, `dose_context`, `source_url`. Curated values override taxonomy values where present.

Interface: `AdditiveDB.get(e_number: str) -> AdditiveInfo | None`

---

## Backend Routes

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/` | `search_page` | Search box |
| GET | `/search?q=...` | `search_results` | Product list (up to 10) |
| GET | `/product/{off_id}` | `product_score` | Full score page |
| GET | `/healthz` | `health_check` | Docker health check |

### Template structure

```
templates/
  base.html      shared layout, nav, CSS links
  search.html    search box
  results.html   product match list
  product.html   score page (main UI)
  error.html     OFF unreachable, not found, etc.
```

---

## Frontend

### Product score page layout (top to bottom)

1. **Product header** — name, brand, thumbnail, confidence badge (`High / Medium / Low confidence`) with tooltip listing reasons, "View on Open Food Facts" link.
2. **Overall score** — large number (0–100) with label ("Good" / "Mixed" / "Poor"). Copy: *"Based on the weights below."* Not the dominant element on the page.
3. **Weight sliders** — three labelled sliders (Nutrition / Additives / Processing). Moving any slider instantly recalculates the overall score. "Reset to defaults" link.
4. **Dimension cards** — one per dimension, ordered by weight (highest first). Each card shows:
   - Label + score (0–100)
   - Input derivation: `"Nutri-Score C → 60"` or `"NOVA group 4 → 0"`
   - One-sentence summary
   - "Positives" section (green, always visible)
   - Collapsible "Flags" section with `EvidenceCard` entries (risk level chip, evidence summary, dose/context, source link)
5. **Footer** — OFF data source credit, licence note, informational disclaimer.

### JS (`static/js/scorer.js`, ~100 lines)

- Reads embedded `<script type="application/json" id="score-data">` on page load.
- Wires three range inputs.
- On every `input` event: recalculates weighted total, updates score display and card order.
- Weights always sum to 100 (proportional redistribution).
- No framework, no build step.

### CSS (`static/css/style.css`)

- Hand-written, no framework.
- CSS custom properties for colours and spacing (easy to retheme).
- Colour palette: white/off-white background, teal/green accent. Typography-led layout with generous spacing.
- Dimension cards use colour-coded left borders (green = good, amber = moderate, red = poor) matching `RiskLevel`.

---

## Deployment

### Project structure

```
vera/
  app/
    main.py
    off_client.py
    models.py
    additive_db.py
    scoring/
      __init__.py
      protocol.py
      tables.py
      food_engine.py
      nutrition_scorer.py
      additive_scorer.py
      nova_scorer.py
  data/
    additives_off_taxonomy.json
    additives_curated.yaml
  templates/
  static/
    css/style.css
    js/scorer.js
  docs/
    design/specs/
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
```

### Docker

- Base image: `python:3.12-slim`
- Runs: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- `docker-compose.yml` for local dev: mounts source, enables `--reload`
- Same image deploys unchanged to Fly.io, Railway, Render, etc.

### Configuration (environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `OFF_USER_AGENT` | `"VeraApp/1.0"` | Sent to OFF API per their policy |
| `OFF_REQUEST_TIMEOUT` | `8` | Seconds before timeout |
| `OFF_CACHE_TTL` | `300` | In-process cache TTL in seconds |
| `DEFAULT_WEIGHT_NUTRITION` | `0.5` | Default nutrition dimension weight |
| `DEFAULT_WEIGHT_ADDITIVES` | `0.3` | Default additives dimension weight |
| `DEFAULT_WEIGHT_NOVA` | `0.2` | Default NOVA/processing weight |

All documented in `.env.example`. No secrets in v1.

---

## Out of scope for v1

- Barcode scanning
- User accounts / saved products
- Cosmetics scoring (module slot is reserved; engine just isn't written yet)
- Persistent database
- Authentication
- Admin interface
