from app.models import DimensionScore, NormalisedProduct
from app.scoring.tables import NOVA_TO_SCORE

_SUMMARIES: dict[int | None, str] = {
    1: "Unprocessed or minimally processed — best choice for processing level.",
    2: "Processed culinary ingredient — typically fine in context.",
    3: "Processed food — moderate level of industrial processing.",
    4: "Ultra-processed — associated with negative health outcomes in population studies.",
    None: "NOVA group data unavailable for this product.",
}

_POSITIVES: dict[int, str] = {
    1: "Unprocessed or minimally processed food.",
    2: "Processed culinary ingredient — low industrial processing.",
}


class NovaScorer:
    def score(self, product: NormalisedProduct) -> DimensionScore:
        group = product.nova_group
        if group not in NOVA_TO_SCORE:
            group = None

        raw_score = NOVA_TO_SCORE.get(group, 50)
        input_label = f"NOVA group {group}" if group else "NOVA group unavailable"

        positives: list[str] = []
        if group in _POSITIVES:
            positives.append(_POSITIVES[group])

        return DimensionScore(
            id="nova",
            label="Processing Level",
            score=raw_score,
            input_label=input_label,
            input_value=raw_score,
            weight_default=0.2,
            summary=_SUMMARIES[group],
            positives=positives,
            flags=[],
        )
