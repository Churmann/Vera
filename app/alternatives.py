import asyncio
from dataclasses import dataclass

from app.models import NormalisedProduct, OFFError
from app.scoring.food_engine import FoodScoringEngine, weighted_overall


@dataclass
class Alternative:
    off_id: str
    name: str
    brand: str | None
    image_url: str | None
    score: int
    band: str  # "good" | "mixed" | "poor"


def _band(score: int) -> str:
    if score >= 70:
        return "good"
    if score >= 40:
        return "mixed"
    return "poor"


async def _fetch_many(off_client, codes: list[str]) -> list[NormalisedProduct]:
    """Fetch products concurrently, skipping any that fail."""
    results = await asyncio.gather(
        *(off_client.fetch_product(c) for c in codes), return_exceptions=True
    )
    return [r for r in results if isinstance(r, NormalisedProduct)]


async def find_better_alternatives(
    off_client,
    engine: FoodScoringEngine,
    product: NormalisedProduct,
    current_score: int,
    *,
    max_results: int = 4,
    candidate_pool: int = 12,
    max_levels: int = 3,
) -> list[Alternative]:
    """Same-category products that score strictly better than ``product``.

    Searches the most-specific category first, broadening one level at a time
    (up to ``max_levels``) until at least two better alternatives are found.
    Returns the best ``max_results``, highest score first.
    """
    tags = _ordered_category_tags(product.categories)
    if not tags:
        return []

    best: list[Alternative] = []
    for tag in tags[:max_levels]:
        try:
            codes = await off_client.search_category(tag, page_size=candidate_pool)
        except OFFError:
            continue

        seen: set[str] = {product.off_id}
        unique = [c for c in codes if not (c in seen or seen.add(c))]

        alts: list[Alternative] = []
        for p in await _fetch_many(off_client, unique):
            score = weighted_overall(engine.score(p))
            if score > current_score:
                alts.append(Alternative(p.off_id, p.name, p.brand, p.image_url, score, _band(score)))
        alts.sort(key=lambda a: a.score, reverse=True)

        if len(alts) >= 2:
            return alts[:max_results]
        if len(alts) > len(best):
            best = alts

    return best[:max_results]


def _ordered_category_tags(categories: list[str]) -> list[str]:
    """English category tags, most-specific first.

    OFF orders categories_tags broad → specific, so reversing puts the most
    specific category first. Non-``en:`` tags are dropped.
    """
    en_tags = [c for c in categories if c.startswith("en:")]
    return list(reversed(en_tags))
