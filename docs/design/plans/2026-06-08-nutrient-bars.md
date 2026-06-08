# Per-nutrient Transparency Bars Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show per-nutrient bars (sugar, salt, saturated fat, fibre, protein, energy per 100 g) inside the expanded Nutritional Quality section, on sourced low→high scales, without changing the Nutri-Score scoring.

**Architecture:** OFF nutriments are parsed in `off_client._normalise` onto `NormalisedProduct`. A new pure module `app/nutrition_bars.py` turns those raw values + a beverage flag into `NutrientBar` view models using verified FSA (food/drink) and EU fibre thresholds. `NutritionScorer` attaches the bars to the nutrition `DimensionScore` (grade→score logic untouched); `presentation` carries them onto the `FactorRow`; `product.html` renders them.

**Tech Stack:** Python 3, FastAPI, Jinja2, pytest, respx.

**Commit policy (per user instruction "show me the rendered bars before committing"):** Build all tasks and get the full suite green, but **defer git commits** until after browser verification (Task 8). Work stays on the already-checked-out `feat/nutrient-bars` branch (master is untouched). The spec is already committed.

---

### Task 1: Model layer

**Files:**
- Modify: `app/models.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from app.models import NutrientBar, NormalisedProduct, DimensionScore


def test_nutrient_bar_defaults():
    bar = NutrientBar(
        key="sugars", label="Sugar", present=True, amount=2.4, unit="g",
        kind="negative", band="low", band_label="Low", marker_pct=16.0,
    )
    assert bar.ticks == []
    assert bar.caption == ""
    assert bar.source_key == ""


def test_normalised_product_nutriment_fields_default_empty():
    p = NormalisedProduct(
        off_id="x", name="X", brand=None, nutriscore_grade=None, nova_group=None,
        additives=[], ingredients_text=None, image_url=None, raw_off_url="u",
    )
    assert p.nutriments == {}
    assert p.is_beverage is False


def test_dimension_score_nutrient_bars_default_empty():
    d = DimensionScore(
        id="nutrition", label="Nutritional Quality", score=60,
        input_label="Nutri-Score C", input_value=60, weight_default=0.5,
        summary="", positives=[], flags=[],
    )
    assert d.nutrient_bars == []
    assert d.nutrient_basis == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -k "nutrient or nutriment" -v`
Expected: FAIL — `ImportError: cannot import name 'NutrientBar'`.

- [ ] **Step 3: Write minimal implementation**

In `app/models.py`, add the dataclass (place it above `DimensionScore`):

```python
@dataclass
class NutrientBar:
    key: str                 # "sugars" | "salt" | "saturated_fat" | "fibre" | "protein" | "energy_kcal"
    label: str               # "Sugar", "Saturated fat", ...
    present: bool
    amount: float | None
    unit: str                # "g" | "kcal"
    kind: str                # "negative" | "higher_better" | "neutral" | "missing"
    band: str                # colour tone token: "low" | "moderate" | "high" | "none"
    band_label: str          # display word: "Low" | "Medium" | "High" | "Source" | ""
    marker_pct: float        # 0–100, clamped
    ticks: list[str] = field(default_factory=list)
    caption: str = ""
    source_key: str = ""     # "fsa" | "eu_fibre" | ""
```

In `NormalisedProduct`, add after `categories`:

```python
    nutriments: dict[str, float] = field(default_factory=dict)
    is_beverage: bool = False
```

In `DimensionScore`, add after `meaning`:

```python
    nutrient_bars: list[NutrientBar] = field(default_factory=list)
    nutrient_basis: str = ""   # "per 100 g" | "per 100 ml" | ""
```

In `tests/conftest.py`, extend `make_product` defaults so existing/new tests can pass nutriments/is_beverage:

```python
        defaults = dict(
            off_id="test123", name="Test Product", brand="Test Brand",
            nutriscore_grade=None, nova_group=None, additives=[],
            ingredients_text=None, image_url=None,
            raw_off_url="https://world.openfoodfacts.org/product/test123/",
            nutriments={}, is_beverage=False,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -k "nutrient or nutriment" -v`
Expected: PASS (3 tests).

---

### Task 2: `nutrition_bars.build()` — core logic

**Files:**
- Create: `app/nutrition_bars.py`
- Test: `tests/test_nutrition_bars.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_nutrition_bars.py`:

```python
import pytest

from app.nutrition_bars import build


def _bars(make_product, **kw):
    return {b.key: b for b in build(make_product(**kw))}


def test_food_sugar_bands(make_product):
    assert _bars(make_product, nutriments={"sugars": 2.4})["sugars"].band_label == "Low"
    assert _bars(make_product, nutriments={"sugars": 12.0})["sugars"].band_label == "Medium"
    assert _bars(make_product, nutriments={"sugars": 30.0})["sugars"].band_label == "High"


def test_food_sugar_boundaries_inclusive_low_and_high(make_product):
    # 5.0 is the documented top of Low; 22.5 the top of Medium.
    assert _bars(make_product, nutriments={"sugars": 5.0})["sugars"].band_label == "Low"
    assert _bars(make_product, nutriments={"sugars": 22.5})["sugars"].band_label == "Medium"


def test_salt_and_satfat_food_bands(make_product):
    assert _bars(make_product, nutriments={"salt": 0.18})["salt"].band_label == "Low"
    assert _bars(make_product, nutriments={"salt": 2.0})["salt"].band_label == "High"
    assert _bars(make_product, nutriments={"saturated_fat": 2.1})["saturated_fat"].band_label == "Medium"


def test_drink_column_switches_band(make_product):
    # 4.0 g sugar is Low as a food (<=5) but Medium as a drink (>2.5).
    assert _bars(make_product, nutriments={"sugars": 4.0})["sugars"].band_label == "Low"
    drink = _bars(make_product, nutriments={"sugars": 4.0}, is_beverage=True)
    assert drink["sugars"].band_label == "Medium"


def test_drink_satfat_high_threshold_is_2_5_not_8_75(make_product):
    # Regression guard: drink saturated-fat HIGH is >2.5 g/100 ml (8.75 is total fat).
    b = _bars(make_product, nutriments={"saturated_fat": 3.0}, is_beverage=True)["saturated_fat"]
    assert b.band_label == "High"
    b2 = _bars(make_product, nutriments={"saturated_fat": 2.0}, is_beverage=True)["saturated_fat"]
    assert b2.band_label == "Medium"


def test_marker_piecewise_and_clamped(make_product):
    # Each zone is a third. value at low_max sits at ~33%; far over high_min clamps to 100.
    at_lowmax = _bars(make_product, nutriments={"sugars": 5.0})["sugars"].marker_pct
    assert 32.0 <= at_lowmax <= 34.0
    huge = _bars(make_product, nutriments={"sugars": 90.0})["sugars"].marker_pct
    assert huge == 100.0


def test_fibre_higher_better_bands_and_tone(make_product):
    low = _bars(make_product, nutriments={"fibre": 2.0})["fibre"]
    src = _bars(make_product, nutriments={"fibre": 4.0})["fibre"]
    high = _bars(make_product, nutriments={"fibre": 7.0})["fibre"]
    assert (low.band_label, low.band) == ("Low", "high")        # little fibre -> red tone
    assert (src.band_label, src.band) == ("Source", "moderate")
    assert (high.band_label, high.band) == ("High", "low")      # lots of fibre -> sage tone
    assert high.kind == "higher_better"
    assert high.source_key == "eu_fibre"


def test_protein_and_energy_are_neutral(make_product):
    bars = _bars(make_product, nutriments={"protein": 9.2, "energy_kcal": 432})
    assert bars["protein"].kind == "neutral"
    assert bars["protein"].band == "none"
    assert bars["protein"].band_label == ""
    assert "no official" in bars["protein"].caption
    assert bars["energy_kcal"].kind == "neutral"
    assert bars["energy_kcal"].unit == "kcal"


def test_missing_nutrient_emits_missing_bar(make_product):
    bars = _bars(make_product, nutriments={"sugars": 2.0})
    assert bars["salt"].kind == "missing"
    assert bars["salt"].present is False


def test_all_missing_returns_empty_list(make_product):
    assert build(make_product(nutriments={})) == []


def test_order_is_fixed(make_product):
    keys = [b.key for b in build(make_product(nutriments={
        "sugars": 1, "salt": 1, "saturated_fat": 1, "fibre": 1, "protein": 1, "energy_kcal": 1,
    }))]
    assert keys == ["sugars", "salt", "saturated_fat", "fibre", "protein", "energy_kcal"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_nutrition_bars.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.nutrition_bars'`.

- [ ] **Step 3: Write the implementation**

Create `app/nutrition_bars.py`:

```python
"""Per-nutrient transparency bars for the Nutritional Quality dimension.

A read-only layer over the raw OFF nutriments — it never affects scoring.
Sugar, salt and saturated fat use the UK FSA / Department of Health
front-of-pack traffic-light cutoffs (separate food / drink columns); fibre uses
the EU Reg. 1924/2006 nutrition-claim thresholds; protein and energy are shown
neutrally because no recognised per-100g threshold exists for them.
"""

from app.models import NormalisedProduct, NutrientBar

# FSA front-of-pack cutoffs as (low_max, high_min). Foods per 100 g; drinks per
# 100 ml. Low = value <= low_max; High = value > high_min; Medium is between.
# Source: gov.uk "Front of pack nutrition labelling guidance" (FSA / DoH).
_FSA_FOOD = {
    "sugars": (5.0, 22.5),
    "salt": (0.3, 1.5),
    "saturated_fat": (1.5, 5.0),
}
_FSA_DRINK = {
    "sugars": (2.5, 11.25),
    "salt": (0.3, 0.75),
    "saturated_fat": (0.75, 2.5),
}

# EU Reg. 1924/2006 fibre claims (per 100 g): "source" >= 3 g, "high" >= 6 g.
_FIBRE = (3.0, 6.0)

# (key, label, unit, kind) in fixed reading order.
_SPEC = [
    ("sugars", "Sugar", "g", "negative"),
    ("salt", "Salt", "g", "negative"),
    ("saturated_fat", "Saturated fat", "g", "negative"),
    ("fibre", "Fibre", "g", "higher_better"),
    ("protein", "Protein", "g", "neutral"),
    ("energy_kcal", "Energy", "kcal", "neutral"),
]

# Neutral bars have no published cutoff — the reference is a visual placement
# scale only, and is labelled as such in the caption.
_NEUTRAL_REF = {"protein": 25.0, "energy_kcal": 900.0}
_NEUTRAL_CAPTION = {
    "protein": "more is better · no official per-100g threshold",
    "energy_kcal": "FSA gives energy no colour — shown for context",
}


def _fmt(n: float) -> str:
    """Compact number for tick labels: 22.5 -> '22.5', 5.0 -> '5'."""
    return f"{n:g}"


def _piecewise_pct(v: float, low_max: float, high_min: float) -> float:
    """Marker position 0–100 with each of the three zones occupying a third, so
    every band stays visually readable. The unbounded top zone spans high_min →
    2*high_min then clamps at the right edge (the numeric label stays exact)."""
    if v <= low_max:
        frac = (v / low_max) / 3 if low_max else 0.0
    elif v <= high_min:
        frac = (1 + (v - low_max) / (high_min - low_max)) / 3
    else:
        over = min((v - high_min) / high_min, 1.0) if high_min else 1.0
        frac = (2 + over) / 3
    return round(max(0.0, min(frac, 1.0)) * 100, 1)


def _negative_bar(key, label, unit, value, low_max, high_min) -> NutrientBar:
    if value <= low_max:
        band, band_label = "low", "Low"
    elif value <= high_min:
        band, band_label = "moderate", "Medium"
    else:
        band, band_label = "high", "High"
    return NutrientBar(
        key=key, label=label, present=True, amount=value, unit=unit,
        kind="negative", band=band, band_label=band_label,
        marker_pct=_piecewise_pct(value, low_max, high_min),
        ticks=["0", _fmt(low_max), _fmt(high_min), f"{_fmt(high_min * 2)} {unit}+"],
        source_key="fsa",
    )


def _fibre_bar(value) -> NutrientBar:
    low_max, high_min = _FIBRE
    # Higher is better, so the colour tone is reversed vs negative nutrients:
    # little fibre = red tone, lots = sage tone. band_label describes the amount.
    if value < low_max:
        band, band_label = "high", "Low"
    elif value < high_min:
        band, band_label = "moderate", "Source"
    else:
        band, band_label = "low", "High"
    return NutrientBar(
        key="fibre", label="Fibre", present=True, amount=value, unit="g",
        kind="higher_better", band=band, band_label=band_label,
        marker_pct=_piecewise_pct(value, low_max, high_min),
        ticks=["0", "3 g source", "6 g high", "12 g+"],
        caption="more is better", source_key="eu_fibre",
    )


def _neutral_bar(key, label, unit, value) -> NutrientBar:
    ref = _NEUTRAL_REF[key]
    pct = round(min(value / ref, 1.0) * 100, 1) if ref else 0.0
    return NutrientBar(
        key=key, label=label, present=True, amount=value, unit=unit,
        kind="neutral", band="none", band_label="",
        marker_pct=pct, ticks=[], caption=_NEUTRAL_CAPTION[key], source_key="",
    )


def _missing_bar(key, label, unit) -> NutrientBar:
    return NutrientBar(
        key=key, label=label, present=False, amount=None, unit=unit,
        kind="missing", band="none", band_label="", marker_pct=0.0,
        ticks=[], caption="Not provided by Open Food Facts", source_key="",
    )


def build(product: NormalisedProduct) -> list[NutrientBar]:
    """Build the per-nutrient bars for a product. Returns [] when none of the
    six target nutrients are present (the page then shows a single honest line)."""
    n = product.nutriments
    thresholds = _FSA_DRINK if product.is_beverage else _FSA_FOOD
    bars: list[NutrientBar] = []
    for key, label, unit, kind in _SPEC:
        if key not in n:
            bars.append(_missing_bar(key, label, unit))
        elif kind == "negative":
            low_max, high_min = thresholds[key]
            bars.append(_negative_bar(key, label, unit, n[key], low_max, high_min))
        elif kind == "higher_better":
            bars.append(_fibre_bar(n[key]))
        else:
            bars.append(_neutral_bar(key, label, unit, n[key]))
    if all(b.kind == "missing" for b in bars):
        return []
    return bars
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_nutrition_bars.py -v`
Expected: PASS (all tests).

---

### Task 3: OFF client — parse nutriments + beverage flag

**Files:**
- Modify: `app/off_client.py` (`_PRODUCT_FIELDS`, `_normalise`, add helpers)
- Test: `tests/test_off_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_off_client.py`:

```python
from app.off_client import _normalise


def test_normalise_parses_nutriments():
    p = _normalise("123", {
        "product_name": "Test",
        "nutriments": {
            "sugars_100g": 2.4, "salt_100g": "0.18", "saturated-fat_100g": 1.1,
            "fiber_100g": 3.2, "proteins_100g": 8.0, "energy-kcal_100g": 250,
        },
    })
    assert p.nutriments["sugars"] == 2.4
    assert p.nutriments["salt"] == 0.18          # string coerced to float
    assert p.nutriments["saturated_fat"] == 1.1
    assert p.nutriments["fibre"] == 3.2
    assert p.nutriments["protein"] == 8.0
    assert p.nutriments["energy_kcal"] == 250


def test_normalise_omits_missing_and_nonnumeric_nutriments():
    p = _normalise("123", {"product_name": "Test", "nutriments": {
        "sugars_100g": "", "salt_100g": "n/a",
    }})
    assert "sugars" not in p.nutriments
    assert "salt" not in p.nutriments


def test_normalise_energy_falls_back_to_kj():
    p = _normalise("123", {"product_name": "Test", "nutriments": {"energy_100g": 1046}})
    # 1046 kJ / 4.184 = 250.0 kcal
    assert p.nutriments["energy_kcal"] == 250.0


def test_normalise_detects_beverage_from_categories():
    p = _normalise("123", {"product_name": "Cola", "categories_tags": ["en:sodas", "en:beverages"]})
    assert p.is_beverage is True


def test_normalise_non_beverage_default():
    p = _normalise("123", {"product_name": "Bar", "categories_tags": ["en:snacks"]})
    assert p.is_beverage is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_off_client.py -k "nutriment or beverage or energy" -v`
Expected: FAIL — `AttributeError`/`KeyError` (nutriments not populated).

- [ ] **Step 3: Write the implementation**

In `app/off_client.py`, add `nutriments` to the product fields:

```python
_PRODUCT_FIELDS = "code,product_name,brands,image_url,nutriscore_grade,nova_group,additives_tags,ingredients_text,categories_tags,nutriments"
```

Add helpers near the other module-level parse helpers (e.g. above `_normalise`):

```python
# OFF nutriment key -> our internal key. All are the per-100g variants.
_NUTRIMENT_KEYS = {
    "sugars": "sugars_100g",
    "salt": "salt_100g",
    "saturated_fat": "saturated-fat_100g",
    "fibre": "fiber_100g",        # OFF uses US spelling; British fallback below
    "protein": "proteins_100g",
}
_BEVERAGE_HINTS = ("beverages", "drinks")


def _to_float(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def _parse_nutriments(raw: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for internal, off_key in _NUTRIMENT_KEYS.items():
        v = _to_float(raw.get(off_key))
        if v is None and internal == "fibre":
            v = _to_float(raw.get("fibre_100g"))
        if v is not None:
            out[internal] = v
    # Energy: OFF reports kcal as energy-kcal_100g; fall back to kJ (energy_100g).
    kcal = _to_float(raw.get("energy-kcal_100g"))
    if kcal is None:
        kj = _to_float(raw.get("energy_100g"))
        if kj is not None:
            kcal = round(kj / 4.184, 1)
    if kcal is not None:
        out["energy_kcal"] = kcal
    return out


def _is_beverage(categories_tags: list[str]) -> bool:
    return any(any(h in tag for h in _BEVERAGE_HINTS) for tag in categories_tags)
```

In `_normalise`, add the two fields to the `NormalisedProduct(...)` construction (after `categories=...`):

```python
        nutriments=_parse_nutriments(p.get("nutriments") or {}),
        is_beverage=_is_beverage(p.get("categories_tags") or []),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_off_client.py -v`
Expected: PASS (new + existing tests).

---

### Task 4: NutritionScorer attaches bars

**Files:**
- Modify: `app/scoring/nutrition_scorer.py`
- Test: `tests/scoring/test_nutrition_scorer.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/scoring/test_nutrition_scorer.py`:

```python
def test_score_attaches_nutrient_bars(make_product):
    dim = NutritionScorer().score(make_product(
        nutriscore_grade="C", nutriments={"sugars": 2.4, "salt": 0.1},
    ))
    assert dim.score == 60                      # scoring unchanged
    keys = [b.key for b in dim.nutrient_bars]
    assert keys[0] == "sugars"
    assert dim.nutrient_basis == "per 100 g"


def test_score_uses_drink_basis_for_beverages(make_product):
    dim = NutritionScorer().score(make_product(
        nutriscore_grade="E", is_beverage=True, nutriments={"sugars": 10.0},
    ))
    assert dim.nutrient_basis == "per 100 ml"


def test_score_without_nutriments_has_no_bars(make_product):
    dim = NutritionScorer().score(make_product(nutriscore_grade="B"))
    assert dim.nutrient_bars == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/scoring/test_nutrition_scorer.py -k "bars or basis" -v`
Expected: FAIL — `nutrient_bars` empty / `nutrient_basis` not set.

- [ ] **Step 3: Write the implementation**

In `app/scoring/nutrition_scorer.py`, add the import at the top:

```python
from app.nutrition_bars import build as build_nutrient_bars
```

In the returned `DimensionScore(...)`, add (after `meaning=_MEANING,`):

```python
            nutrient_bars=build_nutrient_bars(product),
            nutrient_basis=("per 100 ml" if product.is_beverage else "per 100 g"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/scoring/test_nutrition_scorer.py -v`
Expected: PASS (new + existing).

---

### Task 5: presentation carries bars onto the row

**Files:**
- Modify: `app/presentation.py` (`FactorRow`, `_dimension_row`)
- Test: `tests/test_presentation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_presentation.py` (uses the existing scoring engine / fixtures in that file; adapt the helper name if the file builds results differently — check the top of the file first):

```python
from app.models import DimensionScore, NutrientBar


def _nutrition_dim_with_bars():
    return DimensionScore(
        id="nutrition", label="Nutritional Quality", score=60,
        input_label="Nutri-Score C", input_value=60, weight_default=0.5,
        summary="Average.", positives=[], flags=[],
        nutrient_bars=[NutrientBar(
            key="sugars", label="Sugar", present=True, amount=2.4, unit="g",
            kind="negative", band="low", band_label="Low", marker_pct=16.0,
        )],
        nutrient_basis="per 100 g",
    )


def test_dimension_row_carries_nutrient_bars():
    from app.presentation import _dimension_row
    row = _dimension_row(_nutrition_dim_with_bars(), "nutrition")
    assert len(row.nutrient_bars) == 1
    assert row.nutrient_bars[0].key == "sugars"
    assert row.nutrient_basis == "per 100 g"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_presentation.py -k "nutrient" -v`
Expected: FAIL — `FactorRow` has no `nutrient_bars`.

- [ ] **Step 3: Write the implementation**

In `app/presentation.py`, add to `FactorRow` (after the `positives` field):

```python
    # Nutrition dimension only: per-nutrient transparency bars + their basis.
    nutrient_bars: list = field(default_factory=list)
    nutrient_basis: str = ""
```

In `_dimension_row`, add to the `FactorRow(...)` construction:

```python
        nutrient_bars=list(dim.nutrient_bars),
        nutrient_basis=dim.nutrient_basis,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_presentation.py -v`
Expected: PASS.

---

### Task 6: Template rendering

**Files:**
- Modify: `templates/product.html`
- Test: `tests/test_routes.py` (assert markup appears for a product with nutriments)

- [ ] **Step 1: Write the failing test**

Match the existing `tests/test_routes.py` pattern: a **sync** function with the
`@respx.mock` decorator and `with TestClient(app) as client`. Omit
`categories_tags` so the alternatives lookup short-circuits without an unmocked
search request (this is why the existing product-route tests pass). Add:

```python
@respx.mock
def test_product_page_renders_nutrient_bars():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Granola", "nutriscore_grade": "c", "nova_group": 3,
            "additives_tags": [], "ingredients_text": "Oats", "image_url": None,
            "nutriments": {"sugars_100g": 21.3, "salt_100g": 0.2,
                           "saturated-fat_100g": 2.1, "fiber_100g": 7.4,
                           "proteins_100g": 9.2, "energy-kcal_100g": 432},
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    assert response.status_code == 200
    body = response.text
    assert "nutrient-bar" in body          # the bar component rendered
    assert "Saturated fat" in body
    assert "per 100 g" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_routes.py -k "nutrient_bars" -v`
Expected: FAIL — `"nutrient-bar"` not in body.

- [ ] **Step 3: Write the implementation**

In `templates/product.html`, add a macro near the top (after `factor_row`):

```jinja
{#- One per-nutrient bar: header (label · amount · band chip), zoned/neutral
    track with marker, tick labels, optional caption. Colour is always paired
    with the band word so it never relies on colour alone. -#}
{% macro nutrient_bar(bar) -%}
<div class="nutrient-bar nutrient-bar--{{ bar.kind }}{% if not bar.present %} nutrient-bar--missing{% endif %}">
  <div class="nutrient-bar-head">
    <span class="nutrient-bar-name">{{ bar.label }}{% if bar.caption and bar.present and bar.kind != 'negative' %} <span class="nutrient-bar-caption">· {{ bar.caption }}</span>{% endif %}</span>
    {% if bar.present %}
    <span class="nutrient-bar-meta">
      <span class="nutrient-bar-amount">{{ '%g'|format(bar.amount) }}<span class="nutrient-bar-unit"> {{ bar.unit }}</span></span>
      {% if bar.band_label %}<span class="nutrient-band nutrient-band--{{ bar.band }}">{{ bar.band_label }}</span>{% endif %}
    </span>
    {% else %}
    <span class="nutrient-bar-amount nutrient-bar-amount--missing">Not provided</span>
    {% endif %}
  </div>
  {% if bar.present %}
  <div class="nutrient-track nutrient-track--{{ bar.kind }} nutrient-track--{{ bar.band }}">
    {% if bar.kind in ('negative', 'higher_better') %}
    <span class="nutrient-zone nutrient-zone--lo"></span>
    <span class="nutrient-zone nutrient-zone--mid"></span>
    <span class="nutrient-zone nutrient-zone--hi"></span>
    {% endif %}
    <span class="nutrient-marker" style="left: {{ bar.marker_pct }}%"></span>
  </div>
  {% if bar.ticks %}
  <div class="nutrient-ticks">{% for t in bar.ticks %}<span>{{ t }}</span>{% endfor %}</div>
  {% endif %}
  {% else %}
  <div class="nutrient-track nutrient-track--empty" aria-hidden="true"></div>
  {% endif %}
</div>
{%- endmacro %}
```

In the `factor_row` macro, inside `{% if row.kind == "dimension" %}`, **immediately after** the `factor-derivation` paragraph, insert:

```jinja
    {% if row.icon_category == "nutrition" %}
      {% if row.nutrient_bars %}
      <div class="nutrient-bars">
        {% for bar in row.nutrient_bars %}{{ nutrient_bar(bar) }}{% endfor %}
      </div>
      <p class="nutrient-source">
        Scale {{ row.nutrient_basis }}. Thresholds:
        <a href="https://www.gov.uk/government/publications/front-of-pack-nutrition-labelling-guidance" target="_blank" rel="noopener">UK FSA front-of-pack</a>
        (sugar, salt, saturated fat) ·
        <a href="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32006R1924" target="_blank" rel="noopener">EU Reg. 1924/2006</a>
        (fibre). Protein &amp; energy have no official per-100g threshold.
      </p>
      {% else %}
      <p class="factor-text nutrient-missing-all">Per-nutrient detail isn't available for this product on Open Food Facts.</p>
      {% endif %}
    {% endif %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_routes.py -k "nutrient_bars" -v`
Expected: PASS.

- [ ] **Step 5: Full suite green**

Run: `python -m pytest -q`
Expected: all tests pass.

---

### Task 7: Styling

**Files:**
- Modify: `static/css/style.css` (append a new section)

- [ ] **Step 1: Append the bar styles**

Add at the end of `static/css/style.css`:

```css
/* ---- Per-nutrient transparency bars (Nutritional Quality, expanded) ---- */
.nutrient-bars { margin: .75rem 0 .25rem; }
.nutrient-bar { margin: 0 0 1rem; }
.nutrient-bar-head { display: flex; align-items: baseline; justify-content: space-between; gap: .5rem; margin-bottom: .4rem; }
.nutrient-bar-name { font-size: .88rem; font-weight: 600; }
.nutrient-bar-caption { font-weight: 400; font-size: .76rem; color: var(--color-text-muted); }
.nutrient-bar-meta { display: inline-flex; align-items: baseline; gap: .5rem; }
.nutrient-bar-amount { font-size: .88rem; font-variant-numeric: tabular-nums; }
.nutrient-bar-unit { color: var(--color-text-muted); font-weight: 400; font-size: .8rem; }
.nutrient-bar-amount--missing { color: var(--color-text-muted); font-style: italic; }
.nutrient-band { font-size: .7rem; font-weight: 600; padding: .06rem .45rem; border-radius: 999px; white-space: nowrap; }
.nutrient-band--low { color: var(--risk-low); background: var(--risk-low-bg); }
.nutrient-band--moderate { color: var(--risk-moderate); background: var(--risk-moderate-bg); }
.nutrient-band--high { color: var(--risk-high); background: var(--risk-high-bg); }

.nutrient-track { position: relative; display: flex; height: 9px; border-radius: 999px; overflow: hidden; background: var(--risk-unknown-bg); }
.nutrient-zone { height: 100%; flex: 1 1 33.333%; }
/* Soft tints of the muted risk palette — calm, not a loud traffic light. */
.nutrient-track--negative .nutrient-zone--lo  { background: #d8e3db; }
.nutrient-track--negative .nutrient-zone--mid { background: #ece0c8; }
.nutrient-track--negative .nutrient-zone--hi  { background: #e7d2cd; }
/* higher-is-better (fibre) reverses the tints: low amount on the left is the poor end. */
.nutrient-track--higher_better .nutrient-zone--lo  { background: #e7d2cd; }
.nutrient-track--higher_better .nutrient-zone--mid { background: #ece0c8; }
.nutrient-track--higher_better .nutrient-zone--hi  { background: #d8e3db; }
.nutrient-track--neutral { background: #e6e7ea; }
.nutrient-track--empty { background: repeating-linear-gradient(45deg, #f0f1f3, #f0f1f3 6px, #f7f7f8 6px, #f7f7f8 12px); }

.nutrient-marker { position: absolute; top: -3px; width: 3px; height: 15px; border-radius: 2px; background: var(--color-text); box-shadow: 0 0 0 2px var(--color-surface); transform: translateX(-50%); }
.nutrient-ticks { display: flex; justify-content: space-between; margin-top: .3rem; font-size: .66rem; color: var(--color-text-muted); font-variant-numeric: tabular-nums; }

.nutrient-source { margin-top: .9rem; font-size: .74rem; color: var(--color-text-muted); }
.nutrient-source a { color: var(--color-accent); }
.nutrient-missing-all { color: var(--color-text-muted); font-style: italic; }
```

- [ ] **Step 2: Sanity check**

Run: `python -m pytest -q`
Expected: still green (CSS doesn't affect tests; confirms nothing broke).

---

### Task 8: Browser verification + commit

**Files:** none (verification + git)

- [ ] **Step 1: Start the app**

Run (background): `python -m uvicorn app.main:app --port 8000`
Confirm `GET /healthz` returns `{"status":"ok"}`.

- [ ] **Step 2: Fetch the three target products and confirm the bars render**

Open in the browser (real OFF data):
- Nutella (food, high sugar + sat fat): `http://localhost:8000/product/3017620422003`
- Coca-Cola (drink, exercises drink thresholds): `http://localhost:8000/product/5449000000996`
- A product missing some nutriments: pick one during verification (e.g. a product with no fibre/energy) and note its barcode.

For each: expand the Nutritional Quality row; confirm bars show actual amounts, correct bands/colours, the marker position, drink-vs-food basis text, missing rows where applicable, and the sources footnote. Programmatically confirm markup with a quick fetch (e.g. `curl -s .../product/3017620422003 | grep -c nutrient-bar`).

- [ ] **Step 3: Show the user**

Present the three rendered pages / screenshots to the user and get approval. Fix any visual issues (new CSS version) before proceeding.

- [ ] **Step 4: Commit (only after approval)**

```bash
git add app/ templates/ static/ tests/
git commit -m "feat: per-nutrient transparency bars in Nutritional Quality

Sugar/salt/saturated fat on UK FSA front-of-pack thresholds (food &
drink columns), fibre on EU 1924/2006, protein & energy neutral.
Read-only layer over OFF nutriments; Nutri-Score scoring unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 5: Finish the branch**

Use superpowers:finishing-a-development-branch to choose merge / PR / cleanup.

---

## Notes for the implementer

- Run tests with `python -m pytest` from the `yuka-app` directory.
- The Nutri-Score → score mapping in `nutrition_scorer.py` must not change — only the two new keyword arguments are added to the returned `DimensionScore`.
- `'%g'|format(x)` in Jinja mirrors the Python `_fmt` used for ticks, so amounts and tick numbers format consistently.
