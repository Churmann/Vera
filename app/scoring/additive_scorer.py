from app.additive_db import AdditiveDB
from app.models import DimensionScore, EvidenceCard, NormalisedProduct, RiskLevel

_RISK_ORDER = {RiskLevel.HIGH: 0, RiskLevel.MODERATE: 1, RiskLevel.LOW: 2, RiskLevel.UNKNOWN: 3}
_DEDUCTIONS = {RiskLevel.HIGH: 30, RiskLevel.MODERATE: 10, RiskLevel.LOW: 0, RiskLevel.UNKNOWN: 0}


class AdditiveScorer:
    def __init__(self, db: AdditiveDB):
        self._db = db

    def score(self, product: NormalisedProduct) -> DimensionScore:
        cards: list[EvidenceCard] = []
        for e_num in product.additives:
            info = self._db.get(e_num)
            if info:
                cards.append(EvidenceCard(
                    name=info.name,
                    e_number=e_num,
                    risk_level=info.risk_level,
                    evidence_summary=info.evidence_summary or "No detailed evidence summary available.",
                    dose_context=info.dose_context or "Dose/context data not available.",
                    source_url=info.source_url,
                ))
            else:
                cards.append(EvidenceCard(
                    name=e_num.upper(),
                    e_number=e_num,
                    risk_level=RiskLevel.UNKNOWN,
                    evidence_summary="This additive is not in our database.",
                    dose_context="",
                    source_url=None,
                ))

        cards.sort(key=lambda c: _RISK_ORDER[c.risk_level])
        raw_score = max(0, 100 - sum(_DEDUCTIONS[c.risk_level] for c in cards))

        positives: list[str] = []
        if not cards:
            positives.append("No additives detected.")
        elif all(c.risk_level in (RiskLevel.LOW, RiskLevel.UNKNOWN) for c in cards):
            positives.append("No high- or moderate-risk additives detected.")

        high = sum(1 for c in cards if c.risk_level == RiskLevel.HIGH)
        moderate = sum(1 for c in cards if c.risk_level == RiskLevel.MODERATE)
        count = len(product.additives)

        return DimensionScore(
            id="additives",
            label="Additives",
            score=raw_score,
            input_label=f"{count} additive{'s' if count != 1 else ''} detected",
            input_value=raw_score,
            weight_default=0.3,
            summary=_summary(high, moderate, count),
            positives=positives,
            flags=cards,
        )


def _summary(high: int, moderate: int, total: int) -> str:
    if total == 0:
        return "No additives detected."
    if high > 0:
        return f"{total} additive{'s' if total != 1 else ''} detected, including {high} flagged as high-risk."
    if moderate > 0:
        return f"{total} additive{'s' if total != 1 else ''} detected, including {moderate} flagged as moderate-risk."
    return f"{total} additive{'s' if total != 1 else ''} detected, all low-risk or unclassified."
