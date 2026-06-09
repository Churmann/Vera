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
