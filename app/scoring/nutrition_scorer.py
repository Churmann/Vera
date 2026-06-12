from app.models import DimensionScore, NormalisedProduct
from app.nutrition_bars import build as build_nutrient_bars
from app.scoring.tables import NUTRISCORE_TO_SCORE

_SUMMARIES: dict[str | None, str] = {
    "A": "Excellent nutritional profile.",
    "B": "Good nutritional profile.",
    "C": "Average nutritional profile.",
    "D": "Below-average nutritional profile.",
    "E": "Poor nutritional profile.",
    None: "Nutri-Score data unavailable for this product.",
}

# Plain-language classification shown prominently in place of "Nutri-Score X".
_PLAIN_BAND: dict[str | None, str] = {
    "A": "Excellent",
    "B": "Good",
    "C": "Average",
    "D": "Below average",
    "E": "Poor",
    None: "Nutritional quality unknown",
}

# Plain explanation of the metric itself, shown behind the info icon.
_MEANING = (
    "Nutri-Score grades overall nutritional quality from A (best) to E (worst), "
    "based on sugar, salt, saturated fat, and beneficial nutrients like fibre."
)


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

        panel = build_nutrient_bars(product)

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
            plain_band=_PLAIN_BAND[grade],
            meaning=_MEANING,
            nutrient_bars=panel.bars,
            nutrient_basis=("per 100 ml" if product.is_beverage else "per 100 g"),
            nutrient_note=panel.note,
            nutrient_missing_summary=panel.missing_summary,
        )
