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
    # Optional honest status shown in place of evidence when there is no
    # verified source_url (e.g. "EFSA re-evaluation in progress").
    pending_note: str | None = None
    # Functional category (colour, sweetener, preservative, emulsifier, acid,
    # mineral, glazing, flavour, other) used to pick a card icon.
    category: str = "other"


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
    category: str = "other"


@dataclass
class DimensionScore:
    id: str
    label: str
    score: int            # 0–100
    input_label: str      # e.g. "Nutri-Score C"
    input_value: int      # e.g. 60 — shown as "Nutri-Score C → 60"
    weight_default: float
    summary: str
    positives: list[str]
    flags: list[EvidenceCard]


@dataclass
class ScoreResult:
    dimensions: list[DimensionScore]
    confidence: ConfidenceLevel
    confidence_notes: list[str]
    off_url: str
    score_cap: int | None = None
    score_cap_reasons: list[str] = field(default_factory=list)
