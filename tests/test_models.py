from app.models import RiskLevel, ConfidenceLevel, OFFError, NormalisedProduct, AdditiveInfo, EvidenceCard


def test_risk_level_values():
    assert RiskLevel.LOW.value == "low"
    assert RiskLevel.MODERATE.value == "moderate"
    assert RiskLevel.HIGH.value == "high"
    assert RiskLevel.UNKNOWN.value == "unknown"


def test_confidence_level_values():
    assert ConfidenceLevel.HIGH.value == "high"
    assert ConfidenceLevel.MEDIUM.value == "medium"
    assert ConfidenceLevel.LOW.value == "low"


def test_off_error_is_exception():
    err = OFFError("timed out", "timeout")
    assert isinstance(err, Exception)
    assert err.kind == "timeout"
    assert str(err) == "timed out"


def test_normalised_product_stores_fields():
    p = NormalisedProduct(
        off_id="123", name="Nutella", brand="Ferrero",
        nutriscore_grade="E", nova_group=4,
        additives=["e322", "e407"],
        ingredients_text="Sugar, palm oil",
        image_url=None,
        raw_off_url="https://world.openfoodfacts.org/product/123/",
    )
    assert p.off_id == "123"
    assert p.nova_group == 4
    assert "e322" in p.additives


def test_additive_info_defaults():
    info = AdditiveInfo(e_number="e330", name="Citric acid", risk_level=RiskLevel.LOW)
    assert info.evidence_summary == ""
    assert info.dose_context == ""
    assert info.source_url is None


def test_evidence_card_stores_fields():
    card = EvidenceCard(
        name="Tartrazine", e_number="e102", risk_level=RiskLevel.MODERATE,
        evidence_summary="Linked to hyperactivity in children.",
        dose_context="Effect observed at high doses; typical food exposure is lower.",
        source_url="https://efsa.europa.eu",
    )
    assert card.name == "Tartrazine"
    assert card.risk_level == RiskLevel.MODERATE
