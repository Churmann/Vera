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
        self.kind = kind  # "timeout", "rate_limited", "not_found", "network_error", "no_credentials", "write_failed"


@dataclass
class AdditiveInfo:
    e_number: str
    name: str
    risk_level: RiskLevel
    evidence_summary: str = ""
    dose_context: str = ""
    source_url: str | None = None
    # An optional second supporting source, e.g. the EFSA evaluation backing the
    # ADI when the primary source_url is a primary study. Rendered as an extra link.
    secondary_source_url: str | None = None
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
    # OFF categories_tags, ordered broad → most-specific (as OFF returns them).
    categories: list[str] = field(default_factory=list)
    # OFF countries_tags (e.g. "en:united-kingdom") — the markets the product is sold in.
    countries_tags: list[str] = field(default_factory=list)
    nutriments: dict[str, float] = field(default_factory=dict)
    is_beverage: bool = False


@dataclass
class EvidenceCard:
    name: str
    e_number: str
    risk_level: RiskLevel
    evidence_summary: str
    dose_context: str
    source_url: str | None
    secondary_source_url: str | None = None
    category: str = "other"


@dataclass
class NutrientBar:
    key: str                 # "sugars" | "salt" | "saturated_fat" | "fibre" | "protein" | "energy_kcal"
    label: str               # "Sugar", "Saturated fat", ...
    present: bool
    amount: float | None
    unit: str                # "g" | "kcal"
    kind: str                # "negative" | "higher_better" | "neutral" | "missing"
    band: str                # colour tone token: "low" | "moderate" | "high" | "none"
    band_label: str          # display word: "Low" | "Medium" | "High" | "Source" | ""
    marker_pct: float        # 0–100, clamped
    ticks: list[str] = field(default_factory=list)
    caption: str = ""
    source_key: str = ""     # "fsa" | "eu_fibre" | ""


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
    # Plain-language band shown prominently in place of jargon, e.g.
    # "Ultra-processed" / "Poor". The technical term (input_label) is kept
    # alongside as smaller supporting detail.
    plain_band: str = ""
    # One-line plain explanation of what this metric means, surfaced behind an
    # info icon and repeated in the expandable detail (education over jargon).
    meaning: str = ""
    nutrient_bars: list[NutrientBar] = field(default_factory=list)
    nutrient_basis: str = ""   # "per 100 g" | "per 100 ml" | ""
    # Calm explanation of crowd-sourced data gaps. ``nutrient_note`` accompanies a
    # few no-data rows; ``nutrient_missing_summary`` replaces them with one honest
    # line when most/all values are absent (mutually exclusive in practice).
    nutrient_note: str = ""
    nutrient_missing_summary: str = ""


@dataclass
class ScoreResult:
    dimensions: list[DimensionScore]
    confidence: ConfidenceLevel
    confidence_notes: list[str]
    off_url: str
    score_cap: int | None = None
    score_cap_reasons: list[str] = field(default_factory=list)
