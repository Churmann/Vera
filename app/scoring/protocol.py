from typing import Protocol

from app.models import NormalisedProduct, ScoreResult


class ScoringEngine(Protocol):
    def score(self, product: NormalisedProduct) -> ScoreResult: ...
