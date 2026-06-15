import json
import re
from pathlib import Path

import yaml

from app.models import AdditiveInfo, RiskLevel

_RISK_MAP: dict[str, RiskLevel] = {
    "low": RiskLevel.LOW,
    "moderate": RiskLevel.MODERATE,
    "high": RiskLevel.HIGH,
    "unknown": RiskLevel.UNKNOWN,
}

# Specific E-numbers whose function does not match their numeric range.
_CATEGORY_OVERRIDES: dict[int, str] = {
    170: "mineral",        # calcium carbonate (sits in the colour range)
    322: "emulsifier",     # lecithin (sits in the antioxidant range)
    420: "sweetener",      # sorbitol (polyol in the 400s)
    421: "sweetener",      # mannitol (polyol in the 400s)
    507: "acid",           # hydrochloric acid (in the 500s)
}


def infer_category(e_number: str) -> str:
    """Infer a functional category from the E-number, using the standard
    E-number ranges with a few well-known exceptions. Defaults to "other"."""
    m = re.match(r"e(\d+)", str(e_number).lower())
    if not m:
        return "other"
    n = int(m.group(1))

    if n in _CATEGORY_OVERRIDES:
        return _CATEGORY_OVERRIDES[n]
    if 950 <= n <= 969:
        return "sweetener"
    if n in (260, 261, 262, 263, 270, 296, 297):  # acids inside the preservative block
        return "acid"
    if 300 <= n <= 399:                            # antioxidants & acidity regulators
        return "acid"
    if 574 <= n <= 579:                            # gluconic acid & gluconates
        return "acid"
    if 100 <= n <= 199:
        return "colour"
    if 200 <= n <= 299:
        return "preservative"
    if 400 <= n <= 499:
        return "emulsifier"
    if 500 <= n <= 599:
        return "mineral"
    if 600 <= n <= 699:
        return "flavour"
    if 900 <= n <= 914:
        return "glazing"
    return "other"


class AdditiveDB:
    def __init__(self, taxonomy_path: Path, curated_path: Path):
        self._db: dict[str, AdditiveInfo] = {}
        self._load(taxonomy_path, curated_path)

    def get(self, e_number: str) -> AdditiveInfo | None:
        return self._db.get(e_number.lower())

    def _load(self, taxonomy_path: Path, curated_path: Path) -> None:
        with open(taxonomy_path, encoding="utf-8") as f:
            for entry in json.load(f):
                e_num = entry["e_number"].lower()
                self._db[e_num] = AdditiveInfo(
                    e_number=e_num,
                    name=entry["name"],
                    risk_level=_RISK_MAP.get(entry.get("risk_level", "unknown"), RiskLevel.UNKNOWN),
                    category=entry.get("category") or infer_category(e_num),
                )

        with open(curated_path, encoding="utf-8") as f:
            curated = yaml.safe_load(f) or {}

        for e_num, data in curated.items():
            e_num = e_num.lower()
            existing = self._db.get(e_num)
            self._db[e_num] = AdditiveInfo(
                e_number=e_num,
                name=data.get("name", existing.name if existing else e_num),
                risk_level=_RISK_MAP.get(
                    data.get("risk_level", "unknown"),
                    existing.risk_level if existing else RiskLevel.UNKNOWN,
                ),
                evidence_summary=data.get("evidence_summary", ""),
                dose_context=data.get("dose_context", ""),
                source_url=data.get("source_url"),
                secondary_source_url=data.get("secondary_source_url"),
                pending_note=data.get("pending_note"),
                category=data.get("category") or infer_category(e_num),
            )
