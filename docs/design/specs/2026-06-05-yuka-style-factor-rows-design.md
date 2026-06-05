# Yuka-style grouped factor rows — design

Date: 2026-06-05

## Problem

The product score page shows three flat dimension cards (Nutritional Quality,
Additives, Processing Level). We want a cleaner, Yuka-style layout that groups
factors into **Negatives** and **Positives**, while keeping all existing content
and the server-rendered, accessible, muted-token design.

## Decision

Restructure **only** the dimension/factor presentation (the `.dimensions`
section). Everything else on the page is preserved unchanged:

- overall score + "Mixed/Good/Poor" label + score-cap notice
- fixed-weights panel + "Why these weights?" disclosure
- better-alternatives section
- the additive evidence cards with evidence / dose / source links

### Row model (flatten)

Each Negatives/Positives row is a `.factor-row`. Three kinds:

1. **Dimension rows** — Nutritional Quality and Processing Level. Value shows the
   grade (`Nutri-Score E`, `NOVA 4`). Expanding reveals the existing derivation
   (`Nutri-Score E → 20/100`), summary, and positives.
2. **Additive rows** — one per EvidenceCard, keeping the existing category icon
   and risk chip (the risk word is the value). Expanding reveals
   evidence / dose / source, exactly as today.
3. **Statement rows** — the Additives dimension's positive statements
   ("No additives detected", "No high- or moderate-risk additives detected").
   Non-expandable. Preserves that content and gives the no-additives case a
   visible positive.

The rolled-up "Additives 90/100" number and its one-line summary sentence are
dropped (the individual additive rows + statement convey the same). The
Additives dimension still appears in the weights panel (30%) and cap logic.

### Grouping & banding

`band` is derived per factor and drives both the group and the dot colour:

| Source | good | moderate | poor | unknown |
|--------|------|----------|------|---------|
| dimension score | ≥ 70 | 40–69 | < 40 | — |
| additive risk | Low | Moderate | High | Unknown |

- **Positives** = band `good` (score ≥ 70 / risk Low).
- **Negatives** = band `moderate`, `poor`, or `unknown` (mixed/poor → Negatives,
  matching Yuka). Unavailable data (score 50) and unclassified additives land in
  Negatives as honest mild concerns.

### Display rules

- **Negatives are never capped** — all flagged negatives are always shown.
- **Positives show the first ~5**, with the remainder behind a "Show N more"
  disclosure (`<details>`), so a product with many low-risk additives stays tidy.
- Within a group, dimension rows come before additive rows; additives keep their
  existing risk-sorted order.

### Accessibility & palette

- Dot colours use the existing muted `--risk-low/moderate/high/unknown` tokens
  (sage / amber / muted-red / slate), not the saturated `--color-*`.
- Never colour-alone: the section heading (Negatives/Positives) and the text
  value (grade / risk word) carry the meaning; the dot also gets a
  visually-hidden band label.

## Components / files

- **`app/factors.py`** (new) — pure, testable `build_factor_groups(result)
  -> FactorGroups(negatives, positives)`; `Factor` dataclass; band helpers.
  No I/O, no template logic.
- **`app/main.py`** — compute `factors` in the product route, pass to template.
- **`templates/product.html`** — replace `.dimensions` with `.factors` (two
  groups, empty states, positives disclosure); add a `dimension_icon` macro
  (nutrition = heart, processing = gear) in the existing inline-SVG style; reuse
  `category_icon` for additives.
- **`static/css/style.css`** — replace `.dimension-card*` rules with
  `.factors` / `.factor-group` / `.factor-row` / `.factor-dot`; keep
  `.evidence-body`, `.risk-chip`, `.additive-icon` (reused in row detail).
- **Tests** — new `tests/test_factors.py` (banding, grouping, statement & empty
  cases, positives cap, negatives never capped); extend `tests/test_routes.py`
  with a Negatives/Positives grouping + accessibility assertion. Existing icon /
  risk-chip / weights tests stay green.

## Testing strategy

Unit-test the pure `build_factor_groups` against constructed `ScoreResult`s
(no network). Route tests use the existing `respx` mocks. Verify rendered HTML
contains both group headings, the dimension grade values, additive rows with
category icon + risk chip, and the visually-hidden band labels.
