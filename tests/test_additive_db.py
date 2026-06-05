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


import pytest as _pytest

from app.additive_db import infer_category


@_pytest.mark.parametrize("e_number,expected", [
    ("e100", "colour"),
    ("e150d", "colour"),
    ("e160a", "colour"),
    ("e171", "colour"),
    ("e170", "mineral"),        # calcium carbonate – mineral, not colour
    ("e202", "preservative"),
    ("e250", "preservative"),
    ("e260", "acid"),           # acetic acid sits in the 200s but is an acid
    ("e270", "acid"),
    ("e296", "acid"),
    ("e300", "acid"),
    ("e322", "emulsifier"),     # lecithin numbered in the 300s but is an emulsifier
    ("e330", "acid"),
    ("e385", "acid"),
    ("e407", "emulsifier"),
    ("e471", "emulsifier"),
    ("e472e", "emulsifier"),
    ("e420", "sweetener"),      # sorbitol numbered in the 400s but is a polyol sweetener
    ("e421", "sweetener"),
    ("e500", "mineral"),
    ("e551", "mineral"),
    ("e575", "acid"),           # glucono-delta-lactone
    ("e621", "flavour"),
    ("e631", "flavour"),
    ("e901", "glazing"),
    ("e904", "glazing"),
    ("e951", "sweetener"),
    ("e968", "sweetener"),
    ("e1999", "other"),         # unknown range defaults sensibly
    ("nonsense", "other"),
])
def test_infer_category(e_number, expected):
    assert infer_category(e_number) == expected


def test_curated_category_explicit_overrides_inference(tmp_path):
    curated = {
        "e330": {"name": "Citric acid", "risk_level": "low", "category": "preservative",
                 "source_url": "https://example.com/e330"},
    }
    t = tmp_path / "taxonomy.json"
    c = tmp_path / "curated.yaml"
    t.write_text("[]")
    c.write_text(yaml.dump(curated))
    db = AdditiveDB(t, c)
    assert db.get("e330").category == "preservative"  # explicit wins over inferred "acid"


def test_category_inferred_when_absent(tmp_path):
    curated = {"e330": {"name": "Citric acid", "risk_level": "low",
                        "source_url": "https://example.com/e330"}}
    t = tmp_path / "taxonomy.json"
    c = tmp_path / "curated.yaml"
    t.write_text("[]")
    c.write_text(yaml.dump(curated))
    db = AdditiveDB(t, c)
    assert db.get("e330").category == "acid"


def test_taxonomy_entry_gets_inferred_category(tmp_path):
    t = tmp_path / "taxonomy.json"
    c = tmp_path / "curated.yaml"
    t.write_text('[{"e_number": "e133", "name": "Brilliant Blue", "risk_level": "low"}]')
    c.write_text("{}")
    db = AdditiveDB(t, c)
    assert db.get("e133").category == "colour"


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
