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
