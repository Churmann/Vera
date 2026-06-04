import json
from pathlib import Path

import yaml

from app.models import AdditiveInfo, RiskLevel

_RISK_MAP: dict[str, RiskLevel] = {
    "low": RiskLevel.LOW,
    "moderate": RiskLevel.MODERATE,
    "high": RiskLevel.HIGH,
    "unknown": RiskLevel.UNKNOWN,
}


class AdditiveDB:
    def __init__(self, taxonomy_path: Path, curated_path: Path):
        self._db: dict[str, AdditiveInfo] = {}
        self._load(taxonomy_path, curated_path)

    def get(self, e_number: str) -> AdditiveInfo | None:
        return self._db.get(e_number.lower())

    def _load(self, taxonomy_path: Path, curated_path: Path) -> None:
        with open(taxonomy_path) as f:
            for entry in json.load(f):
                e_num = entry["e_number"].lower()
                self._db[e_num] = AdditiveInfo(
                    e_number=e_num,
                    name=entry["name"],
                    risk_level=_RISK_MAP.get(entry.get("risk_level", "unknown"), RiskLevel.UNKNOWN),
                )

        with open(curated_path) as f:
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
                pending_note=data.get("pending_note"),
            )
