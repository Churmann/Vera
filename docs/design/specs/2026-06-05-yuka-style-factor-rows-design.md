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

- **Negatives** = only the *flagged* factors: dimensions scoring below 70
  (mixed/poor → Negatives, matching Yuka) and **moderate- or high-risk**
  additives. Unavailable dimension data (score 50) sits here as an honest mild
  concern.
- **Positives** = good dimensions (score ≥ 70) plus **low-risk additives** and
  **unclassified (unknown-risk) additives** — the latter are not flagged as
  risky, so they belong with the non-flagged tail. They keep a slate dot and an
  honest "Unknown risk" label; they are never dressed up as "Low".

### Display rules

- **Negatives are never capped** — every flagged negative is always shown.
- **Positive additives show the first ~5**, with the remainder behind a
  "Show N more low-risk additives" disclosure (`<details>`), so a product with
  many harmless additives stays tidy. Dimension rows are never hidden.
- Within a group, dimension rows come before additive rows; additives keep their
  existing risk-sorted order.
- When a product has **no additives**, the Additives dimension's "No additives
  detected" content survives as a single positive summary row. When low-risk
  additives are present, the individual rows convey the reassurance, so the
  redundant blanket "no high/moderate-risk additives" statement is not repeated.

### Accessibility & palette

- Dot colours use the existing muted `--risk-low/moderate/high/unknown` tokens
  (sage / amber / muted-red / slate), not the saturated `--color-*`.
- Never colour-alone: the section heading (Negatives/Positives) and the text
  value (grade / risk word) carry the meaning; the dot also gets a
  visually-hidden band label.

## Components / files

- **`app/presentation.py`** (new) — pure, testable `group_factors(result)
  -> GroupedFactors(negatives, positives, hidden_positives)`; flat `FactorRow`
  dataclass carrying both the collapsed-row fields and the expandable detail.
  No I/O, no template logic.
- **`app/main.py`** — compute `factors = group_factors(result)` in the product
  route and pass it to the template.
- **`templates/product.html`** — replace the `.dimension-card` loop with the
  `#factors` Negatives/Positives section and a `factor_row` macro; add
  `nutrition` (heart) and `processing` (factory) icons to the existing
  `category_icon` macro; reuse it for additives. The enum suffix `(E…)` is
  suppressed when it would merely repeat an unnamed additive's label.
- **`static/css/style.css`** — remove the dead `.dimension-*` / `.evidence-card`
  rules; add `.factor*` styles (rows, muted dots, chevron, group headings,
  "show more" disclosure, `.visually-hidden`); keep the reused `.additive-icon`,
  `.risk-chip`, `.source-link`.
- **Tests** — new `tests/test_presentation.py` (thresholds, risk split,
  evidence/dose/source carried, no-additives summary survives, positives cap with
  remainder hidden, negatives never hidden, tone words); extend
  `tests/test_routes.py` with grouping order, the many-additives cap, and the
  unnamed-additive enum de-duplication. Existing icon / risk-chip / weights tests
  stay green.

## Testing strategy

Unit-test the pure `group_factors` against constructed `ScoreResult`s
(no network). Route tests use the existing `respx` mocks. Verify rendered HTML
contains both group headings, the dimension grade values, additive rows with
category icon + risk chip, and the visually-hidden band labels.
