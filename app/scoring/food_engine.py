from app.models import ConfidenceLevel, NormalisedProduct, ScoreResult
from app.scoring.additive_scorer import AdditiveScorer
from app.scoring.nova_scorer import NovaScorer
from app.scoring.nutrition_scorer import NutritionScorer


class FoodScoringEngine:
    def __init__(self, additive_scorer: AdditiveScorer):
        self._nutrition = NutritionScorer()
        self._additives = additive_scorer
        self._nova = NovaScorer()

    def score(self, product: NormalisedProduct) -> ScoreResult:
        confidence, notes = _confidence(product)
        return ScoreResult(
            dimensions=[
                self._nutrition.score(product),
                self._additives.score(product),
                self._nova.score(product),
            ],
            confidence=confidence,
            confidence_notes=notes,
            off_url=product.raw_off_url,
        )


def _confidence(product: NormalisedProduct) -> tuple[ConfidenceLevel, list[str]]:
    notes: list[str] = []
    if product.nutriscore_grade is None:
        notes.append("Nutri-Score grade not available for this product.")
    if product.nova_group is None:
        notes.append("NOVA group not available for this product.")
    level = [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW][min(len(notes), 2)]
    return level, notes
