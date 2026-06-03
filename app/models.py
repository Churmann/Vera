from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    UNKNOWN = "unknown"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class OFFError(Exception):
    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.message = message
        self.kind = kind  # "timeout", "rate_limited", "not_found", "network_error"


@dataclass
class AdditiveInfo:
    e_number: str
    name: str
    risk_level: RiskLevel
    evidence_summary: str = ""
    dose_context: str = ""
    source_url: str | None = None


@dataclass
class NormalisedProduct:
    off_id: str
    name: str
    brand: str | None
    nutriscore_grade: str | None  # A–E
    nova_group: int | None        # 1–4
    additives: list[str]          # e-numbers e.g. "e330"
    ingredients_text: str | None
    image_url: str | None
    raw_off_url: str


@dataclass
class EvidenceCard:
    name: str
    e_number: str
    risk_level: RiskLevel
    evidence_summary: str
    dose_context: str
    source_url: str | None
