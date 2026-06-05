import json

import pytest
import yaml

from app.additive_db import AdditiveDB
from app.models import ConfidenceLevel
from app.scoring.additive_scorer import AdditiveScorer
from app.scoring.food_engine import FoodScoringEngine


@pytest.fixture
def engine(tmp_path):
    t = tmp_path / "taxonomy.json"
    c = tmp_path / "curated.yaml"
    t.write_text("[]")
    c.write_text("{}")
    db = AdditiveDB(t, c)
    return FoodScoringEngine(additive_scorer=AdditiveScorer(db))


def test_returns_three_dimensions(engine, make_product):
    result = engine.score(make_product(nutriscore_grade="B", nova_group=1))
    assert len(result.dimensions) == 3
    assert {d.id for d in result.dimensions} == {"nutrition", "additives", "nova"}


def test_high_confidence_when_both_present(engine, make_product):
    result = engine.score(make_product(nutriscore_grade="A", nova_group=1))
    assert result.confidence == ConfidenceLevel.HIGH
    assert result.confidence_notes == []


def test_medium_confidence_when_nutriscore_missing(engine, make_product):
    result = engine.score(make_product(nutriscore_grade=None, nova_group=2))
    assert result.confidence == ConfidenceLevel.MEDIUM
    assert len(result.confidence_notes) == 1


def test_medium_confidence_when_nova_missing(engine, make_product):
    result = engine.score(make_product(nutriscore_grade="C", nova_group=None))
    assert result.confidence == ConfidenceLevel.MEDIUM
    assert len(result.confidence_notes) == 1


def test_low_confidence_when_both_missing(engine, make_product):
    result = engine.score(make_product(nutriscore_grade=None, nova_group=None))
    assert result.confidence == ConfidenceLevel.LOW
    assert len(result.confidence_notes) == 2


def test_empty_additives_does_not_lower_confidence(engine, make_product):
    result = engine.score(make_product(nutriscore_grade="A", nova_group=1, additives=[]))
    assert result.confidence == ConfidenceLevel.HIGH


def test_off_url_preserved(engine, make_product):
    product = make_product(nutriscore_grade="C", nova_group=2)
    result = engine.score(product)
    assert result.off_url == product.raw_off_url


# --- score cap ---

def test_no_cap_for_decent_product(engine, make_product):
    result = engine.score(make_product(nutriscore_grade="B", nova_group=2))
    assert result.score_cap is None
    assert result.score_cap_reasons == []


def test_cap_fires_for_nova4(engine, make_product):
    result = engine.score(make_product(nutriscore_grade="B", nova_group=4))
    assert result.score_cap == 35
    assert any("ultra-processed" in r for r in result.score_cap_reasons)


def test_cap_fires_for_nutriscore_e(engine, make_product):
    result = engine.score(make_product(nutriscore_grade="E", nova_group=2))
    assert result.score_cap == 35
    assert any("nutritionally poor" in r for r in result.score_cap_reasons)


def test_cap_fires_for_both_triggers(engine, make_product):
    """Coke profile: Nutri-Score E + NOVA 4 — both reasons should appear."""
    result = engine.score(make_product(nutriscore_grade="E", nova_group=4))
    assert result.score_cap == 35
    assert len(result.score_cap_reasons) == 2


def test_cap_value_is_applied_by_weighted_score():
    """Weighted average would be 70 (B + no additives + NOVA 1) — no cap."""
    from app.main import _weighted_score
    from app.models import DimensionScore, EvidenceCard
    dims = [
        DimensionScore("nutrition", "N", 80, "x", 80, 0.5, "", [], []),
        DimensionScore("additives", "A", 100, "x", 100, 0.3, "", [], []),
        DimensionScore("nova", "P", 75, "x", 75, 0.2, "", [], []),
    ]
    assert _weighted_score(dims, None) == 85  # 80*0.5 + 100*0.3 + 75*0.2
    assert _weighted_score(dims, 35) == 35


def test_nutriscore_d_does_not_trigger_cap(engine, make_product):
    """Nutri-Score D maps to score 40, above NUTRITION_CAP_THRESHOLD of 20 — no cap."""
    result = engine.score(make_product(nutriscore_grade="D", nova_group=2))
    assert result.score_cap is None


# --- weighted_overall: shared single source of truth for the overall score ---

def test_weighted_overall_computes_from_result_dimensions(engine, make_product):
    from app.scoring.food_engine import weighted_overall
    result = engine.score(make_product(nutriscore_grade="B", nova_group=1))
    expected = round(sum(d.score * d.weight_default for d in result.dimensions))
    assert weighted_overall(result) == expected


def test_weighted_overall_applies_score_cap(engine, make_product):
    """A capped product's overall must not exceed the cap."""
    from app.scoring.food_engine import weighted_overall
    result = engine.score(make_product(nutriscore_grade="E", nova_group=4))
    assert result.score_cap == 35
    assert weighted_overall(result) == 35
