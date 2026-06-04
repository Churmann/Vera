import json

import pytest
import yaml

from app.additive_db import AdditiveDB
from app.models import RiskLevel


@pytest.fixture
def db_files(tmp_path):
    taxonomy = [
        {"e_number": "e330", "name": "Citric acid", "risk_level": "low"},
        {"e_number": "e102", "name": "Tartrazine", "risk_level": "moderate"},
    ]
    curated = {
        "e102": {
            "name": "Tartrazine",
            "risk_level": "moderate",
            "evidence_summary": "Linked to hyperactivity.",
            "dose_context": "At doses achievable through diet.",
            "source_url": "https://example.com/e102",
        }
    }
    t = tmp_path / "taxonomy.json"
    c = tmp_path / "curated.yaml"
    t.write_text(json.dumps(taxonomy))
    c.write_text(yaml.dump(curated))
    return t, c


def test_loads_taxonomy_entry(db_files):
    db = AdditiveDB(*db_files)
    info = db.get("e330")
    assert info is not None
    assert info.name == "Citric acid"
    assert info.risk_level == RiskLevel.LOW


def test_curated_overrides_taxonomy(db_files):
    db = AdditiveDB(*db_files)
    info = db.get("e102")
    assert info.evidence_summary == "Linked to hyperactivity."
    assert info.source_url == "https://example.com/e102"


def test_missing_entry_returns_none(db_files):
    db = AdditiveDB(*db_files)
    assert db.get("e999") is None


def test_lookup_is_case_insensitive(db_files):
    db = AdditiveDB(*db_files)
    assert db.get("E330") is not None
    assert db.get("E330").name == "Citric acid"


def test_loads_pending_note(tmp_path):
    curated = {
        "e296": {
            "name": "Malic acid",
            "risk_level": "low",
            "source_url": "",
            "pending_note": "EFSA re-evaluation in progress (2024 call for data).",
        }
    }
    t = tmp_path / "taxonomy.json"
    c = tmp_path / "curated.yaml"
    t.write_text("[]")
    c.write_text(yaml.dump(curated))
    db = AdditiveDB(t, c)
    info = db.get("e296")
    assert info.pending_note == "EFSA re-evaluation in progress (2024 call for data)."
    assert not info.source_url


def test_empty_curated_file(tmp_path):
    t = tmp_path / "taxonomy.json"
    c = tmp_path / "curated.yaml"
    t.write_text('[{"e_number": "e330", "name": "Citric acid", "risk_level": "low"}]')
    c.write_text("{}")
    db = AdditiveDB(t, c)
    assert db.get("e330") is not None
