from app.models import (
    ConfidenceLevel,
    DimensionScore,
    EvidenceCard,
    NutrientBar,
    RiskLevel,
    ScoreResult,
)
from app.presentation import (
    MAX_VISIBLE_POSITIVE_ADDITIVES,
    group_factors,
)


def _dim(id, label, score, input_label="x", positives=None, flags=None,
         plain_band="band", meaning="what this means"):
    return DimensionScore(
        id=id, label=label, score=score,
        input_label=input_label, input_value=score, weight_default=0.3,
        summary=f"{label} summary", positives=positives or [], flags=flags or [],
        plain_band=plain_band, meaning=meaning,
    )


def _card(e_number, risk, category="other", secondary_source_url=None):
    return EvidenceCard(
        name=f"Additive {e_number}", e_number=e_number, risk_level=risk,
        evidence_summary="ev", dose_context="dose",
        source_url="http://x" if risk != RiskLevel.UNKNOWN else None,
        secondary_source_url=secondary_source_url,
        category=category,
    )


def _result(nutrition, nova, additive_cards):
    return ScoreResult(
        dimensions=[
            _dim("nutrition", "Nutritional Quality", nutrition),
            _dim("additives", "Additives", 100, flags=additive_cards,
                 meaning="Additives summary meaning"),
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


def test_additive_row_carries_secondary_source():
    cards = [_card("e211", RiskLevel.HIGH, "preservative",
                   secondary_source_url="http://efsa/4433")]
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=cards))
    row = next(r for r in grouped.negatives if r.kind == "additive")
    assert row.secondary_source_url == "http://efsa/4433"


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


def test_dimension_row_leads_with_plain_band_and_keeps_technical_label():
    grouped = group_factors(_result(nutrition=20, nova=100, additive_cards=[]))
    nutrition = next(r for r in grouped.negatives if r.label == "Nutritional Quality")
    # Plain band is carried for prominent display...
    assert nutrition.plain_band == "band"
    # ...the jargon term survives as smaller supporting detail...
    assert nutrition.technical_label == nutrition.value_text or nutrition.technical_label
    # ...and the plain-language explanation rides along for the info icon/body.
    assert nutrition.meaning == "what this means"


def test_dimension_technical_label_comes_from_input_label():
    result = _result(nutrition=20, nova=100, additive_cards=[])
    # input_label defaults to "x" in the _dim helper; it becomes the muted sub-label.
    nutrition = next(r for r in group_factors(result).negatives
                     if r.label == "Nutritional Quality")
    assert nutrition.technical_label == "x"


def test_additive_rows_do_not_repeat_the_generic_additives_tooltip():
    cards = [_card("e211", RiskLevel.HIGH, "preservative")]
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=cards))
    row = next(r for r in grouped.negatives if r.kind == "additive")
    # Individual additive rows self-explain via their own evidence/dose/source,
    # so they must NOT carry the generic dimension tooltip — it would repeat on
    # every row and read as noise when a product has many additives.
    assert row.meaning == ""


def test_additives_explanation_exposed_once_for_the_section():
    cards = [_card("e211", RiskLevel.HIGH, "preservative")]
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=cards))
    # The "what additives means" explanation lives once on the section, not per row.
    assert grouped.additives_meaning == "Additives summary meaning"


def test_no_section_additives_note_when_no_additives():
    # With no additives, the standalone "No additives" dimension row carries its
    # own info icon, so there is no separate section-level note to show.
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=[]))
    assert grouped.additives_meaning == ""


def test_additives_note_anchors_to_negatives_when_an_additive_is_flagged():
    # A flagged additive lands in Negatives, so the contextual explainer attaches
    # there — directly under the additive rows, not floating at the very bottom.
    cards = [_card("e211", RiskLevel.HIGH, "preservative")]
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=cards))
    assert grouped.additives_note_in == "negatives"


def test_additives_note_anchors_to_positives_when_all_low_risk():
    cards = [_card("e322", RiskLevel.LOW, "emulsifier")]
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=cards))
    assert grouped.additives_note_in == "positives"


def test_no_additives_note_anchor_when_no_additives():
    grouped = group_factors(_result(nutrition=80, nova=100, additive_cards=[]))
    assert grouped.additives_note_in == ""


def test_tone_uses_muted_palette_words():
    grouped = group_factors(_result(nutrition=20, nova=100, additive_cards=[]))
    nutrition = next(r for r in grouped.negatives if r.label == "Nutritional Quality")
    assert nutrition.tone == "high"
    assert nutrition.tone_label == "Poor"


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
