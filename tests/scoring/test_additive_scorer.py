import json

import pytest
import yaml

from app.additive_db import AdditiveDB
from app.models import RiskLevel
from app.scoring.additive_scorer import AdditiveScorer


@pytest.fixture
def make_db(tmp_path):
    def _make(taxonomy=None, curated=None):
        t = tmp_path / "taxonomy.json"
        c = tmp_path / "curated.yaml"
        t.write_text(json.dumps(taxonomy or []))
        c.write_text(yaml.dump(curated or {}))
        return AdditiveDB(t, c)
    return _make


def test_no_additives_scores_100(make_db, make_product):
    scorer = AdditiveScorer(make_db())
    result = scorer.score(make_product(additives=[]))
    assert result.score == 100
    assert len(result.flags) == 0
    assert any("no additives" in p.lower() for p in result.positives)


def test_high_risk_additive_deducts_30(make_db, make_product):
    taxonomy = [{"e_number": "e102", "name": "Tartrazine", "risk_level": "high"}]
    scorer = AdditiveScorer(make_db(taxonomy=taxonomy))
    result = scorer.score(make_product(additives=["e102"]))
    assert result.score == 70


def test_moderate_risk_additive_deducts_10(make_db, make_product):
    taxonomy = [{"e_number": "e211", "name": "Sodium benzoate", "risk_level": "moderate"}]
    scorer = AdditiveScorer(make_db(taxonomy=taxonomy))
    result = scorer.score(make_product(additives=["e211"]))
    assert result.score == 90


def test_flags_sorted_high_first(make_db, make_product):
    taxonomy = [
        {"e_number": "e330", "name": "Citric acid", "risk_level": "low"},
        {"e_number": "e102", "name": "Tartrazine", "risk_level": "high"},
    ]
    scorer = AdditiveScorer(make_db(taxonomy=taxonomy))
    result = scorer.score(make_product(additives=["e330", "e102"]))
    assert result.flags[0].risk_level == RiskLevel.HIGH
    assert result.flags[1].risk_level == RiskLevel.LOW


def test_unknown_additive_shows_as_unknown(make_db, make_product):
    scorer = AdditiveScorer(make_db())
    result = scorer.score(make_product(additives=["e999"]))
    assert result.flags[0].risk_level == RiskLevel.UNKNOWN
    assert result.flags[0].e_number == "e999"


def test_score_does_not_go_below_zero(make_db, make_product):
    taxonomy = [{"e_number": f"e{i}", "name": f"E{i}", "risk_level": "high"} for i in range(100, 110)]
    scorer = AdditiveScorer(make_db(taxonomy=taxonomy))
    result = scorer.score(make_product(additives=[f"e{i}" for i in range(100, 110)]))
    assert result.score >= 0


def test_curated_evidence_without_source_is_not_shown(make_db, make_product):
    # An entry whose source_url is empty must not present its evidence narrative
    # as if it were sourced — it falls back to the honest "no evidence" state.
    curated = {
        "e296": {
            "name": "Malic acid",
            "risk_level": "low",
            "evidence_summary": "Naturally occurring acid, generally low concern.",
            "dose_context": "Normal metabolite.",
            "source_url": "",
        }
    }
    scorer = AdditiveScorer(make_db(curated=curated))
    card = scorer.score(make_product(additives=["e296"])).flags[0]
    assert card.name == "Malic acid"
    assert not card.source_url
    assert "low concern" not in card.evidence_summary.lower()
    assert "no detailed evidence" in card.evidence_summary.lower()
    assert card.dose_context == ""


def test_curated_entry_without_source_uses_pending_note(make_db, make_product):
    curated = {
        "e296": {
            "name": "Malic acid",
            "risk_level": "low",
            "evidence_summary": "Should not be shown without a source.",
            "source_url": "",
            "pending_note": "EFSA re-evaluation in progress (2024 call for data).",
        }
    }
    scorer = AdditiveScorer(make_db(curated=curated))
    card = scorer.score(make_product(additives=["e296"])).flags[0]
    assert card.evidence_summary == "EFSA re-evaluation in progress (2024 call for data)."
    assert "should not be shown" not in card.evidence_summary.lower()
    assert not card.source_url


def test_curated_entry_with_source_shows_evidence(make_db, make_product):
    curated = {
        "e330": {
            "name": "Citric acid",
            "risk_level": "low",
            "evidence_summary": "EFSA 2020 found no safety concern.",
            "dose_context": "Normal metabolite.",
            "source_url": "https://example.com/e330",
        }
    }
    scorer = AdditiveScorer(make_db(curated=curated))
    card = scorer.score(make_product(additives=["e330"])).flags[0]
    assert card.evidence_summary == "EFSA 2020 found no safety concern."
    assert card.dose_context == "Normal metabolite."
    assert card.source_url == "https://example.com/e330"


def test_dimension_metadata(make_db, make_product):
    scorer = AdditiveScorer(make_db())
    result = scorer.score(make_product(additives=[]))
    assert result.id == "additives"
    assert result.weight_default == 0.3
