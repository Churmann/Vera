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
