import asyncio
from dataclasses import dataclass

from app.models import NormalisedProduct, OFFError
from app.scoring.food_engine import FoodScoringEngine, uncapped_overall, weighted_overall


@dataclass
class Alternative:
    off_id: str
    name: str
    brand: str | None
    image_url: str | None
    score: int
    band: str  # "good" | "mixed" | "poor"
    reason: str  # short, honest explanation of why it's a better pick


def _band(score: int) -> str:
    if score >= 70:
        return "good"
    if score >= 40:
        return "mixed"
    return "poor"


# Lower number = preferred when two dimensions improved by the same amount.
_DIM_PRIORITY = {"nutrition": 0, "nova": 1, "additives": 2}


def _reason(current: NormalisedProduct, current_dims, candidate: NormalisedProduct, candidate_dims) -> str:
    """Explain why ``candidate`` is a better pick, based on the dimension that
    contributed most to the improvement over ``current`` (weighted by importance,
    so a big nutrition gain isn't masked by a smaller-weight processing change)."""
    current_by_id = {d.id: d.score for d in current_dims}
    improvements = [
        ((d.score - current_by_id.get(d.id, 0)) * d.weight_default, -_DIM_PRIORITY[d.id], d.id)
        for d in candidate_dims
        if d.score - current_by_id.get(d.id, 0) > 0
    ]
    if not improvements:
        return "Better overall score"
    _, _, dim_id = max(improvements)
    if dim_id == "nutrition":
        if candidate.nutriscore_grade and current.nutriscore_grade:
            return f"Better nutrition (Nutri-Score {candidate.nutriscore_grade} vs {current.nutriscore_grade})"
        return "Better nutrition"
    if dim_id == "nova":
        if candidate.nova_group and current.nova_group:
            return f"Less processed (NOVA {candidate.nova_group} vs {current.nova_group})"
        return "Less processed"
    return "Cleaner additives"


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
    """Same-category products that are genuinely better than ``product``.

    ``current_score`` is the current product's *uncapped* weighted score.
    Candidates are ranked and compared on their uncapped score too, so the cap
    (which pins every ultra-processed product in a category to the same number)
    doesn't flatten the comparison — but the score *displayed* on each card stays
    the capped one the user sees elsewhere. Candidates missing NOVA or Nutri-Score
    data are skipped, so we never recommend a product that only looks better for
    lack of data to penalise it.

    Searches the most-specific category first, broadening one level at a time
    (up to ``max_levels``) until at least two better alternatives are found.
    Returns the best ``max_results``, best first.
    """
    tags = _ordered_category_tags(product.categories)
    if not tags:
        return []

    current_dims = engine.score(product).dimensions

    best: list[Alternative] = []
    for tag in tags[:max_levels]:
        try:
            codes = await off_client.search_category(tag, page_size=candidate_pool)
        except OFFError:
            continue

        seen: set[str] = {product.off_id}
        unique = [c for c in codes if not (c in seen or seen.add(c))]

        ranked: list[tuple[int, Alternative]] = []
        for p in await _fetch_many(off_client, unique):
            if p.nova_group is None or p.nutriscore_grade is None:
                continue  # don't recommend products with missing data
            result = engine.score(p)
            rank = uncapped_overall(result)
            if rank > current_score:
                display = weighted_overall(result)
                reason = _reason(product, current_dims, p, result.dimensions)
                ranked.append((rank, Alternative(p.off_id, p.name, p.brand, p.image_url, display, _band(display), reason)))
        ranked.sort(key=lambda t: t[0], reverse=True)
        alts = [a for _, a in ranked]

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
