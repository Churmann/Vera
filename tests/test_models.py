from app.models import RiskLevel, ConfidenceLevel, OFFError


def test_risk_level_values():
    assert RiskLevel.LOW.value == "low"
    assert RiskLevel.MODERATE.value == "moderate"
    assert RiskLevel.HIGH.value == "high"
    assert RiskLevel.UNKNOWN.value == "unknown"


def test_confidence_level_values():
    assert ConfidenceLevel.HIGH.value == "high"
    assert ConfidenceLevel.MEDIUM.value == "medium"
    assert ConfidenceLevel.LOW.value == "low"


def test_off_error_is_exception():
    err = OFFError("timed out", "timeout")
    assert isinstance(err, Exception)
    assert err.kind == "timeout"
    assert str(err) == "timed out"
