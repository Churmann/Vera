from app.models import ConfidenceLevel, NormalisedProduct, ScoreResult
from app.scoring.additive_scorer import AdditiveScorer
from app.scoring.nova_scorer import NovaScorer
from app.scoring.nutrition_scorer import NutritionScorer
from app.scoring.tables import NUTRITION_CAP_THRESHOLD, POOR_SCORE_CAP


class FoodScoringEngine:
    def __init__(self, additive_scorer: AdditiveScorer):
        self._nutrition = NutritionScorer()
        self._additives = additive_scorer
        self._nova = NovaScorer()

    def score(self, product: NormalisedProduct) -> ScoreResult:
        nutrition_dim = self._nutrition.score(product)
        additives_dim = self._additives.score(product)
        nova_dim = self._nova.score(product)
        confidence, notes = _confidence(product)

        cap_reasons: list[str] = []
        if nutrition_dim.score <= NUTRITION_CAP_THRESHOLD:
            cap_reasons.append("nutritionally poor (Nutri-Score D or E)")
        if nova_dim.score == 0:
            cap_reasons.append("ultra-processed (NOVA group 4)")

        return ScoreResult(
            dimensions=[nutrition_dim, additives_dim, nova_dim],
            confidence=confidence,
            confidence_notes=notes,
            off_url=product.raw_off_url,
            score_cap=POOR_SCORE_CAP if cap_reasons else None,
            score_cap_reasons=cap_reasons,
        )


def weighted_score(dims: list, score_cap: int | None) -> int:
    total = round(sum(d.score * d.weight_default for d in dims))
    return min(total, score_cap) if score_cap is not None else total


def weighted_overall(result: ScoreResult) -> int:
    """The single source of truth for a product's overall score (0–100)."""
    return weighted_score(result.dimensions, result.score_cap)


def _confidence(product: NormalisedProduct) -> tuple[ConfidenceLevel, list[str]]:
    notes: list[str] = []
    if product.nutriscore_grade is None:
        notes.append("Nutri-Score grade not available for this product.")
    if product.nova_group is None:
        notes.append("NOVA group not available for this product.")
    level = [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW][min(len(notes), 2)]
    return level, notes
