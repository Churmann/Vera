from app.models import DimensionScore, NormalisedProduct
from app.scoring.tables import NUTRISCORE_TO_SCORE

_SUMMARIES: dict[str | None, str] = {
    "A": "Excellent nutritional profile.",
    "B": "Good nutritional profile.",
    "C": "Average nutritional profile.",
    "D": "Below-average nutritional profile.",
    "E": "Poor nutritional profile.",
    None: "Nutri-Score data unavailable for this product.",
}


class NutritionScorer:
    def score(self, product: NormalisedProduct) -> DimensionScore:
        grade = product.nutriscore_grade.upper().strip() if product.nutriscore_grade else None
        if grade not in NUTRISCORE_TO_SCORE:
            grade = None

        raw_score = NUTRISCORE_TO_SCORE.get(grade, 50)
        input_label = f"Nutri-Score {grade}" if grade else "Nutri-Score unavailable"

        positives: list[str] = []
        if grade in ("A", "B"):
            positives.append("Good overall nutritional balance.")

        return DimensionScore(
            id="nutrition",
            label="Nutritional Quality",
            score=raw_score,
            input_label=input_label,
            input_value=raw_score,
            weight_default=0.5,
            summary=_SUMMARIES[grade],
            positives=positives,
            flags=[],
        )
