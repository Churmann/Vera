"""Turns a ScoreResult into the Negatives / Positives row layout shown on the
product page.

Every factor — the Nutrition and Processing dimensions and each individual
additive — becomes one flat row. A row lands in Negatives when it scores poorly
(dimension below the positive threshold, or a moderate/high-risk additive) and
in Positives otherwise. The detail (derivation/summary for dimensions,
evidence/dose/source for additives) is carried on the row for the template to
reveal behind an expand chevron.
"""

from dataclasses import dataclass, field

from app.models import RiskLevel, ScoreResult

# A dimension scoring at or above this is a Positive; below it, a Negative.
# 70 matches the "Good" cutoff used for the overall score label, so anything
# mixed or poor (amber/red) falls into Negatives.
POSITIVE_THRESHOLD = 70

# Low-risk additives can pile up on harmless products. Show this many positive
# additive rows, then tuck the reassuring long tail behind one disclosure.
# Negatives are never capped.
MAX_VISIBLE_POSITIVE_ADDITIVES = 5

# Muted dot/icon tone per dimension band and per additive risk level. Uses the
# calm risk palette (sage / amber / muted red / slate), never the louder
# good/poor colours.
_RISK_TONE = {
    RiskLevel.LOW: "low",
    RiskLevel.MODERATE: "moderate",
    RiskLevel.HIGH: "high",
    RiskLevel.UNKNOWN: "unknown",
}
_NEGATIVE_RISKS = {RiskLevel.HIGH, RiskLevel.MODERATE}


@dataclass
class FactorRow:
    kind: str            # "dimension" | "additive"
    icon_category: str   # key passed to the category_icon() macro
    label: str
    value_text: str      # short value shown on the collapsed row, e.g. "20/100"
    tone: str            # muted dot/icon tone: low | moderate | high | unknown
    tone_label: str      # text severity word (so we never rely on colour alone)
    # Plain-language education shown on every row: the prominent band, the
    # smaller jargon term, and the one-line "what this means" explanation.
    plain_band: str = ""        # e.g. "Ultra-processed" (dimensions only)
    technical_label: str = ""   # e.g. "NOVA group 4" (dimensions only)
    meaning: str = ""           # one-line plain explanation (info icon + body)
    # Dimension detail.
    derivation: str = ""
    summary: str = ""
    positives: list[str] = field(default_factory=list)
    # Nutrition dimension only: per-nutrient transparency bars + their basis.
    nutrient_bars: list = field(default_factory=list)
    nutrient_basis: str = ""
    # Additive detail.
    e_number: str = ""
    risk_label: str = ""
    evidence_summary: str = ""
    dose_context: str = ""
    source_url: str | None = None


@dataclass
class GroupedFactors:
    negatives: list[FactorRow]
    positives: list[FactorRow]
    # Extra low-risk additive rows shown behind a "show more" disclosure.
    hidden_positives: list[FactorRow] = field(default_factory=list)
    # The plain "what additives means" explanation, revealed by a single subtle
    # "What are additives?" affordance (the rows themselves self-explain, so it is
    # never repeated per row). Empty when there are no additives.
    additives_meaning: str = ""
    # Which group the explainer attaches under, so it sits directly beneath the
    # additive rows rather than floating at the bottom: "negatives" when an
    # additive is flagged, else "positives", else "".
    additives_note_in: str = ""


def _dimension_tone(score: int) -> tuple[str, str]:
    if score >= POSITIVE_THRESHOLD:
        return "low", "Good"
    if score >= 40:
        return "moderate", "Mixed"
    return "high", "Poor"


def _dimension_row(dim, icon_category: str) -> FactorRow:
    tone, tone_label = _dimension_tone(dim.score)
    return FactorRow(
        kind="dimension",
        icon_category=icon_category,
        label=dim.label,
        value_text=f"{dim.score}/100",
        tone=tone,
        tone_label=tone_label,
        plain_band=dim.plain_band,
        technical_label=dim.input_label,
        meaning=dim.meaning,
        derivation=f"{dim.input_label} → {dim.input_value}/100",
        summary=dim.summary,
        positives=list(dim.positives),
        nutrient_bars=list(dim.nutrient_bars),
        nutrient_basis=dim.nutrient_basis,
    )


def _additive_row(card) -> FactorRow:
    tone = _RISK_TONE[card.risk_level]
    return FactorRow(
        kind="additive",
        icon_category=card.category,
        label=card.name,
        value_text=card.risk_level.value.title(),
        tone=tone,
        tone_label=f"{card.risk_level.value.title()} risk",
        e_number=card.e_number,
        risk_label=card.risk_level.value.title(),
        evidence_summary=card.evidence_summary,
        dose_context=card.dose_context,
        source_url=card.source_url,
    )


def _empty_additives_row(dim) -> FactorRow:
    """A single positive row standing in for the Additives dimension when a
    product has no additives, so its "No additives detected" content survives."""
    return FactorRow(
        kind="dimension",
        icon_category="additives",
        label=dim.label,
        value_text=f"{dim.score}/100",
        tone="low",
        tone_label="Good",
        plain_band=dim.plain_band,
        technical_label=dim.input_label,
        meaning=dim.meaning,
        derivation=dim.input_label,
        summary=dim.summary,
        positives=list(dim.positives),
    )


def group_factors(result: ScoreResult) -> GroupedFactors:
    dims = {d.id: d for d in result.dimensions}
    negatives: list[FactorRow] = []
    positives: list[FactorRow] = []

    # Dimensions first, in a stable reading order, so the layout doesn't reshuffle.
    for dim_id, icon in (("nutrition", "nutrition"), ("nova", "processing")):
        dim = dims.get(dim_id)
        if dim is None:
            continue
        row = _dimension_row(dim, icon)
        (positives if dim.score >= POSITIVE_THRESHOLD else negatives).append(row)

    additives = dims.get("additives")
    positive_additives: list[FactorRow] = []
    additives_meaning = ""
    if additives is not None:
        if not additives.flags:
            # The standalone "No additives" row keeps its own info icon.
            positives.append(_empty_additives_row(additives))
        else:
            # flags arrive already sorted high → moderate → low → unknown.
            # The rows self-explain via their own evidence; the generic "what
            # additives means" tooltip is shown once on the section instead, so
            # it never repeats and clutters rows on additive-heavy products.
            additives_meaning = additives.meaning
            for card in additives.flags:
                row = _additive_row(card)
                if card.risk_level in _NEGATIVE_RISKS:
                    negatives.append(row)
                else:
                    positive_additives.append(row)

    visible = positive_additives[:MAX_VISIBLE_POSITIVE_ADDITIVES]
    hidden = positive_additives[MAX_VISIBLE_POSITIVE_ADDITIVES:]

    # Anchor the "What are additives?" explainer under the additive rows: beside
    # the flagged ones (Negatives) when present, otherwise under the low-risk tail.
    if not additives_meaning:
        note_in = ""
    elif any(r.kind == "additive" for r in negatives):
        note_in = "negatives"
    else:
        note_in = "positives"

    return GroupedFactors(
        negatives=negatives,
        positives=positives + visible,
        hidden_positives=hidden,
        additives_meaning=additives_meaning,
        additives_note_in=note_in,
    )
