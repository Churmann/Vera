from app.models import (
    ConfidenceLevel,
    DimensionScore,
    EvidenceCard,
    RiskLevel,
    ScoreResult,
)
from app.presentation import (
    MAX_VISIBLE_POSITIVE_ADDITIVES,
    group_factors,
)


def _dim(id, label, score, input_label="x", positives=None, flags=None):
    return DimensionScore(
        id=id, label=label, score=score,
        input_label=input_label, input_value=score, weight_default=0.3,
        summary=f"{label} summary", positives=positives or [], flags=flags or [],
    )


def _card(e_number, risk, category="other"):
    return EvidenceCard(
        name=f"Additive {e_number}", e_number=e_number, risk_level=risk,
        evidence_summary="ev", dose_context="dose",
        source_url="http://x" if risk != RiskLevel.UNKNOWN else None,
        category=category,
    )


def _result(nutrition, nova, additive_cards):
    return ScoreResult(
        dimensions=[
            _dim("nutrition", "Nutritional Quality", nutrition),
            _dim("additives", "Additives", 100, flags=additive_cards),
            _dim("nova", "Processing Level", nova),
        ],
        confidence=ConfidenceLevel.HIGH, confidence_notes=[], off_url="http://o",
    )


def test_poor_dimensions_go_to_negatives():
    grouped = group_factors(_result(nutrition=20, nova=0, additive_cards=[]))
    labels = [r.label for r in grouped.negatives]
    assert "Nutritional Quality" in labels
    assert "Processing Level" in labels


def test_good_dimensions_go_to_positives():
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=[]))
    labels = [r.label for r in grouped.positives]
    assert "Nutritional Quality" in labels
    assert "Processing Level" in labels


def test_threshold_is_inclusive_at_70():
    grouped = group_factors(_result(nutrition=70, nova=69, additive_cards=[]))
    pos = [r.label for r in grouped.positives]
    neg = [r.label for r in grouped.negatives]
    assert "Nutritional Quality" in pos
    assert "Processing Level" in neg


def test_each_additive_is_its_own_row_split_by_risk():
    cards = [
        _card("e150d", RiskLevel.MODERATE, "colour"),
        _card("e211", RiskLevel.HIGH, "preservative"),
        _card("e322", RiskLevel.LOW, "emulsifier"),
        _card("e330", RiskLevel.UNKNOWN, "acid"),
    ]
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=cards))
    neg_e = {r.e_number for r in grouped.negatives if r.kind == "additive"}
    pos_e = {r.e_number for r in grouped.positives if r.kind == "additive"}
    assert neg_e == {"e150d", "e211"}      # moderate + high
    assert pos_e == {"e322", "e330"}       # low + unknown


def test_additive_row_carries_evidence_dose_source():
    cards = [_card("e211", RiskLevel.HIGH, "preservative")]
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=cards))
    row = next(r for r in grouped.negatives if r.kind == "additive")
    assert row.evidence_summary == "ev"
    assert row.dose_context == "dose"
    assert row.source_url == "http://x"
    assert row.icon_category == "preservative"
    assert row.risk_label == "High"


def test_no_additives_keeps_a_positive_summary_row():
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=[]))
    additives_rows = [r for r in grouped.positives if r.icon_category == "additives"]
    assert len(additives_rows) == 1
    assert "summary" in additives_rows[0].summary.lower() or additives_rows[0].summary


def test_many_low_risk_additives_are_capped_with_remainder_hidden():
    cards = [_card(f"e{i}", RiskLevel.LOW, "other") for i in range(9)]
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=cards))
    visible_additives = [r for r in grouped.positives if r.kind == "additive"]
    assert len(visible_additives) == MAX_VISIBLE_POSITIVE_ADDITIVES
    assert len(grouped.hidden_positives) == 9 - MAX_VISIBLE_POSITIVE_ADDITIVES
    # All nine are still represented somewhere (nothing dropped).
    shown = {r.e_number for r in visible_additives} | {r.e_number for r in grouped.hidden_positives}
    assert len(shown) == 9


def test_negative_additives_are_never_hidden():
    cards = [_card(f"e{i}", RiskLevel.HIGH, "other") for i in range(9)]
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=cards))
    assert len(grouped.negatives) == 9
    assert grouped.hidden_positives == []


def test_tone_uses_muted_palette_words():
    grouped = group_factors(_result(nutrition=20, nova=100, additive_cards=[]))
    nutrition = next(r for r in grouped.negatives if r.label == "Nutritional Quality")
    assert nutrition.tone == "high"
    assert nutrition.tone_label == "Poor"
