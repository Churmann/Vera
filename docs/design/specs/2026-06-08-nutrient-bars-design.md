# Per-nutrient transparency bars — Nutritional Quality

**Date:** 2026-06-08
**Status:** Approved (design)
**Component:** Vera — product score page, Nutritional Quality dimension

## Problem

Vera's Nutritional Quality dimension shows a single Nutri-Score grade (A–E) and a
plain-language band ("Average", "Poor"). It does not show *why* a product earns
that grade. Users — like Yuka's audience — want to see the individual nutrients
behind the rating: how much sugar, salt, saturated fat, fibre, protein, and
energy the product actually contains, and whether each is high or low against a
recognised reference.

## Goal

Add a **transparency layer** of per-nutrient bars inside the expanded
Nutritional Quality section. Each bar shows the product's actual per-100g amount
on a coloured low→high scale with a marker. The bars explain the nutrition; they
do **not** change how it is scored.

## Non-goals / guardrails

- **The Nutri-Score scoring is untouched.** `NutritionScorer` still maps grade
  A–E → 100/80/60/40/20 via `NUTRISCORE_TO_SCORE`, and that number stays the
  headline. No change to weights, the score cap, or the overall score.
- The bars are **read-only**. They never feed back into any score.
- No change to search, category, or alternatives ranking logic.
- Missing-nutrient handling does **not** alter the data-confidence badge (that
  remains about Nutri-Score / NOVA availability). The bars are honest about
  missing values on their own.

## Sourced thresholds (the core of the feature)

Sugar, salt, and saturated fat use the **UK FSA / Department of Health
front-of-pack traffic-light** cutoffs. Foods are judged per 100 g; drinks per
100 ml (lower cutoffs). Verified against the official gov.uk FoP guidance and
independent reproductions (Aberdeen Rowett Institute; WCRF; Heart UK).

**Foods — per 100 g**

| Nutrient      | Low (green) ≤ | High (red) > |
|---------------|--------------:|-------------:|
| Sugars        | 5.0 g         | 22.5 g       |
| Saturated fat | 1.5 g         | 5.0 g        |
| Salt          | 0.3 g         | 1.5 g        |

**Drinks — per 100 ml**

| Nutrient      | Low (green) ≤ | High (red) > |
|---------------|--------------:|-------------:|
| Sugars        | 2.5 g         | 11.25 g      |
| Saturated fat | 0.75 g        | 2.5 g        |
| Salt          | 0.3 g         | 0.75 g       |

> Note: the drink **saturated-fat** high cutoff is 2.5 g/100 ml. The 8.75 g
> figure that appears in some tables is **total fat** (half of the 17.5 g food
> value), not saturated fat — a misaligned-row artifact. Confirmed.

Amber (medium) is the range between Low and High.

**Fibre** — no FSA traffic light exists. Uses **EU Regulation 1924/2006**
nutrition-claim thresholds: "source of fibre" ≥ 3 g/100 g, "high fibre" ≥ 6
g/100 g. Higher is better (green = more).

**Protein** — no recognised per-100g threshold exists. Shown on a **neutral**
scale (no colour judgement), honestly labelled "more is better · no official
per-100g threshold".

**Energy** — FSA deliberately assigns energy **no** traffic-light colour. Shown
**neutral**, value only, labelled "shown for context".

**Citations surfaced in the UI** (small footnote under the bars, real links):
- gov.uk — *Front of pack nutrition labelling guidance* (FSA / DoH) — sugar,
  salt, saturated-fat food & drink cutoffs.
- EU Regulation (EC) No 1924/2006 — fibre claim thresholds.

## Data flow

```
OFF API (nutriments)
  -> off_client._normalise()        # parse 6 values + is_beverage
       -> NormalisedProduct.nutriments: dict[str,float], is_beverage: bool
            -> NutritionScorer.score(product)
                 - grade -> score        (UNCHANGED)
                 - nutrition_bars.build(product)  -> attaches bars
                      -> DimensionScore.nutrient_bars: list[NutrientBar]
                           -> presentation._dimension_row  -> FactorRow.nutrient_bars
                                -> product.html nutrient_bar() macro
```

### 1. `off_client.py`

- Add `nutriments` to `_PRODUCT_FIELDS`.
- In `_normalise()`, parse these OFF keys defensively (values may be string,
  number, or absent; non-numeric/absent are simply omitted), into floats keyed
  by a stable internal name:
  - `sugars_100g` → `sugars`
  - `salt_100g` → `salt`
  - `saturated-fat_100g` → `saturated_fat`
  - `fiber_100g` (fallback `fibre_100g`) → `fibre`
  - `proteins_100g` → `protein`
  - `energy-kcal_100g` (fallback `energy_100g` is kJ — only used if kcal absent,
    converted ÷4.184) → `energy_kcal`
- `is_beverage`: `True` if any tag in `categories_tags` contains `beverages` or
  `drinks`. (OFF reports liquids per 100 g; density ≈ 1, treated as per 100 ml —
  standard approximation, noted in a code comment.)

### 2. `models.py`

- `NormalisedProduct`: add `nutriments: dict[str, float]` (default empty) and
  `is_beverage: bool = False`.
- New `NutrientBar` dataclass (view model produced by `nutrition_bars`):
  - `key: str` (sugars/salt/…)
  - `label: str` ("Sugar", "Saturated fat", …)
  - `present: bool`
  - `amount: float | None`, `unit: str` ("g" / "kcal")
  - `kind: str` — `"negative" | "higher_better" | "neutral" | "missing"`
  - `band: str` — `"low" | "moderate" | "high" | "none"`
  - `band_label: str` — "Low" / "Medium" / "High" / "Source" / "" (text, never
    colour-only)
  - `marker_pct: float` — 0–100, clamped
  - `ticks: list[str]` — labels under the track, e.g. `["0","5","22.5","45 g+"]`
  - `caption: str` — e.g. "more is better · no official per-100g threshold"
  - `source_key: str` — which citation this bar maps to (`"fsa"`/`"eu_fibre"`/`""`)
- `DimensionScore`: add `nutrient_bars: list[NutrientBar]` (default empty).

### 3. New module `app/nutrition_bars.py`

Pure, isolated, fully unit-tested. One public function:

```python
def build(product: NormalisedProduct) -> list[NutrientBar]: ...
```

Internal thresholds table keyed by nutrient and `is_beverage`. For each of the
six target nutrients in fixed reading order
(sugars, salt, saturated_fat, fibre, protein, energy_kcal):

- **Missing** (`key not in product.nutriments`): emit a `missing` bar
  (`present=False`, hatched track, "Not provided" note).
- **Negative** (sugars/salt/saturated_fat): pick threshold column by
  `is_beverage`. 3 equal-width zones (low/med/high). Band by value vs
  `(low_max, high_min)`. Marker position is **piecewise** so each zone occupies
  a third of the track:
  - `v ≤ low_max`: `pct = (v/low_max) · ⅓`
  - `low_max < v ≤ high_min`: `pct = ⅓ + ((v−low_max)/(high_min−low_max)) · ⅓`
  - `v > high_min`: `pct = ⅔ + min((v−high_min)/high_min, 1) · ⅓` (clamped to
    100 at `v ≥ 2·high_min`)
  - Ticks: `["0", low_max, high_min, "{2·high_min} {unit}+"]`.
- **Higher-better, sourced** (fibre): reversed semantics, same piecewise marker
  with boundaries `(3, 6)` and clamp at `12`. Band: `< 3` → high(muted-red) /
  `3–6` → moderate(amber) "Source" / `≥ 6` → low(sage) "High". (Sage = good.)
  Ticks: `["0","3 source","6 high","12 g+"]`.
- **Neutral** (protein, energy): single neutral track, no zones, no band chip.
  Marker `pct = min(v/ref, 1)·100` on a context reference (protein `ref = 25 g`,
  energy `ref = 900 kcal`). Captions:
  - protein: "more is better · no official per-100g threshold"
  - energy: "FSA gives energy no colour — shown for context"

If **all six** nutrients are missing, `build()` returns an empty list and the
template shows a single honest line (see §5).

### 4. `presentation.py`

- `FactorRow`: add `nutrient_bars: list = field(default_factory=list)`.
- `_dimension_row` / `_empty_additives_row`: copy `dim.nutrient_bars` onto the
  row (only the nutrition dimension will have any).

### 5. `templates/product.html`

- New macro `nutrient_bar(bar)` rendering one bar: header (label · amount ·
  band chip), the zoned/neutral track with marker, the ticks row, and any
  caption. Missing bars render the hatched "Not provided" variant.
- In `factor_row`, inside the `kind == "dimension"` body, **after** the
  `factor-derivation` line and **before** `factor-text` (summary), render:
  - if `row.nutrient_bars`: the bars + the sources footnote;
  - elif this is the nutrition row and nutriments were entirely absent: the line
    "Per-nutrient detail isn't available for this product on Open Food Facts."
  - (A simple flag on the row distinguishes "nutrition row, no data" from
    "other dimension".)

### 6. `static/css/style.css`

Add bar styles using existing tokens (`--risk-low/-moderate/-high` + their
`-bg`, `--risk-unknown`, `--color-border`, `--radius`). Zones use soft tints of
the muted risk palette; marker is a dark tick with a surface-coloured halo.
Colour is always paired with the text band word. No new palette entries.

## Testing (TDD — tests written first)

`tests/test_nutrition_bars.py`:
- Food negative bands: sugar 2.4 → Low, 12 → Medium, 30 → High (boundary values
  5.0 and 22.5 land on the documented side).
- Drink thresholds applied when `is_beverage`: assert a clean column switch —
  sugars **4.0 g** is **Low** as a food (≤ 5.0) but **Medium** as a drink
  (> 2.5). Same value, different band purely because `is_beverage` flips the
  threshold column.
- Saturated-fat **drink** high boundary is 2.5 (regression guard against the
  8.75 misalignment).
- Marker piecewise positions incl. clamping at `2·high_min`.
- Fibre higher-better bands at 2 / 4 / 7 → high(red)/Source/High(green).
- Protein & energy: `kind == "neutral"`, no band chip, marker on ref scale.
- Missing nutrient → `missing` bar; all-missing → empty list.

`tests/test_off_client.py` (extend):
- `_normalise` parses nutriments (string, number, missing, kJ-only energy
  fallback).
- `is_beverage` detection from `categories_tags`.

## Manual browser verification (before committing implementation)

Run the app and screenshot the expanded Nutritional Quality section for:
- **Nutella** (food; high sugar + sat fat) — expect red/amber negatives.
- **Coca-Cola** (drink; exercises the drink threshold column).
- **A product missing some nutriments** — expect graceful "Not provided" rows.

## Alternatives considered

- **Build bars in `presentation.py`** (it already receives `product`). Rejected
  in favour of scorer-attaches-bars so all product-derived nutrition data flows
  through one place and presentation stays a pure ScoreResult→rows transform.
