import asyncio
import re
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


# Cap simultaneous OFF product fetches. A whole candidate pool fired at once
# burst-trips the API rate limit (429); a small ceiling keeps us under it.
_MAX_CONCURRENT_FETCHES = 4


def _could_beat(engine: FoodScoringEngine, candidate, current_score: int) -> bool:
    """Upper bound on a candidate's uncapped score from Nutri-Score + NOVA alone,
    assuming a perfect (additive-free) profile. If even that can't exceed the current
    score, the real product can't either, so it isn't worth fetching. Candidates
    missing either field are rejected — we never recommend products with missing data."""
    if candidate.nutriscore_grade is None or candidate.nova_group is None:
        return False
    best_case = NormalisedProduct(
        off_id=candidate.code, name="", brand=None,
        nutriscore_grade=candidate.nutriscore_grade, nova_group=candidate.nova_group,
        additives=[], ingredients_text=None, image_url=None, raw_off_url="",
    )
    return uncapped_overall(engine.score(best_case)) > current_score


async def _fetch_many(off_client, codes: list[str]) -> list[NormalisedProduct]:
    """Fetch products with bounded concurrency, skipping any that fail."""
    sem = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)

    async def _one(code: str):
        async with sem:
            return await off_client.fetch_product(code)

    results = await asyncio.gather(
        *(_one(c) for c in codes), return_exceptions=True
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
            candidates = await off_client.search_category(tag, page_size=candidate_pool)
        except OFFError:
            # A rate-limited/failed search is NOT an empty category. Stop here and
            # return what we already have rather than broadening into a parent
            # category and recommending unrelated products.
            break

        seen: set[str] = {product.off_id}
        unique = [c for c in candidates if not (c.code in seen or seen.add(c.code))]

        # Pre-filter on the Nutri-Score + NOVA the search already gave us: only fetch
        # the full product for candidates that *could* beat the current score even with
        # a perfect additives profile. This keeps the product-endpoint fan-out small
        # enough not to trip its rate limit, while never pruning a genuine improvement
        # (the estimate is an upper bound — real additives can only lower the score).
        to_fetch = [c.code for c in unique if _could_beat(engine, c, current_score)]

        ranked: list[tuple[int, Alternative]] = []
        for p in await _fetch_many(off_client, to_fetch):
            if p.nova_group is None or p.nutriscore_grade is None:
                continue  # don't recommend products with missing data
            result = engine.score(p)
            rank = uncapped_overall(result)
            if rank > current_score:
                display = weighted_overall(result)
                reason = _reason(product, current_dims, p, result.dimensions)
                ranked.append((rank, Alternative(p.off_id, p.name, p.brand, p.image_url, display, _band(display), reason)))
        # Rank descending, breaking ties by off_id so the order is stable across loads.
        ranked.sort(key=lambda t: (-t[0], t[1].off_id))
        alts = [a for _, a in ranked]

        if len(alts) >= 2:
            return alts[:max_results]
        if len(alts) > len(best):
            best = alts

    return best[:max_results]


# Categories so broad they mix unrelated product types — e.g. every drink together,
# or all plant products / all food. Broadening into these is what surfaced juice,
# tea and yogurt as "alternatives" to a cola, so they are never searched.
_TOO_GENERIC_TAGS = frozenset({
    "en:foods",
    "en:groceries",
    "en:beverages",
    "en:beverages-and-beverages-preparations",
    "en:plant-based-foods",
    "en:plant-based-foods-and-beverages",
})

# A canonical OFF category tag is an ``en:`` prefix followed by a lowercase,
# hyphenated ASCII slug. OFF also carries untranslated tags like
# ``en:Pâtes à tartiner`` (capitals/spaces/accents) that don't exist in the search
# index — those must be rejected so they don't waste search levels.
_CANONICAL_EN_TAG = re.compile(r"^en:[a-z0-9-]+$")


def _ordered_category_tags(categories: list[str]) -> list[str]:
    """English category tags, most-specific first.

    OFF orders categories_tags broad → specific, so reversing puts the most
    specific category first. Tags are kept only if they are canonical ``en:`` slugs
    (dropping non-English and malformed/untranslated tags) and not so generic
    (``_TOO_GENERIC_TAGS``) that they mix unrelated product types.
    """
    en_tags = [c for c in categories
               if _CANONICAL_EN_TAG.match(c) and c not in _TOO_GENERIC_TAGS]
    return list(reversed(en_tags))
