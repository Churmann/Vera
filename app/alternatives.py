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


def _upper_bound(engine: FoodScoringEngine, candidate) -> int | None:
    """A candidate's best-case uncapped score from its Nutri-Score + NOVA alone, assuming
    a perfect (additive-free) profile. ``None`` when either field is missing (we never
    recommend products with missing data). Real additives can only lower the score, so this
    is a true upper bound — safe both for pruning candidates that can't win and for
    pre-ranking which ones are worth fully fetching."""
    if candidate.nutriscore_grade is None or candidate.nova_group is None:
        return None
    best_case = NormalisedProduct(
        off_id=candidate.code, name="", brand=None,
        nutriscore_grade=candidate.nutriscore_grade, nova_group=candidate.nova_group,
        additives=[], ingredients_text=None, image_url=None, raw_off_url="",
    )
    return uncapped_overall(engine.score(best_case))


def _could_beat(engine: FoodScoringEngine, candidate, current_score: int) -> bool:
    """Whether a candidate's upper bound exceeds the current score — i.e. whether the real
    product could possibly be a genuine improvement and is therefore worth fetching."""
    ub = _upper_bound(engine, candidate)
    return ub is not None and ub > current_score


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
    candidate_pool: int = 100,
    max_fetch: int = 12,
    max_levels: int | None = None,
) -> list[Alternative]:
    """Same-category products that are genuinely better than ``product``.

    ``current_score`` is the current product's *uncapped* weighted score. Candidates are
    ranked and compared on their uncapped score too, so the cap (which pins every
    ultra-processed product in a category to the same number) doesn't flatten the
    comparison — but the score *displayed* on each card stays the capped one the user
    sees elsewhere. Candidates missing NOVA or Nutri-Score data are skipped.

    Tightest-first, like Yuka: the most-specific kind level is searched first and a
    candidate counts only if it shares *that level's* kind tag. The first (tightest) level
    that yields one or more healthier same-kind matches wins and is returned alone — looser
    levels never dilute it. If a level has none, broaden one level and try again, through
    every reasonable (specific, non-generic) level, so the section is empty only when no
    healthier option exists at any of them. Returns the best ``max_results``, best first.
    """
    tags = _ordered_category_tags(product.categories)
    if not tags:
        return []

    # No specific kind tag at all (only broad groupings) -> we can't establish kinship.
    # Honest empty rather than a loosely-related guess.
    if not _specific_tags(product.categories):
        return []

    current_dims = engine.score(product).dimensions

    levels = tags if max_levels is None else tags[:max_levels]

    # Option A region filter: at each level, search the viewed product's own market(s) first,
    # then fall back to an unfiltered search at that same level before broadening to a looser
    # kind. A foreign same-kind product is a better suggestion than an empty section, but a
    # genuinely available in-market one is better still. With no known market, only the
    # unfiltered pass runs (so non-region products are unaffected).
    product_countries = product.countries_tags
    attempts: list[tuple[str, list[str] | None]] = []
    for tag in levels:
        if product_countries:
            attempts.append((tag, product_countries))
        attempts.append((tag, None))

    for tag, countries in attempts:
        try:
            candidates = await off_client.search_category(
                tag, page_size=candidate_pool, countries=countries)
        except OFFError:
            # A rate-limited/failed search is NOT an empty level. Stop rather than
            # broadening into a looser tag and recommending unrelated products.
            break

        seen: set[str] = {product.off_id}
        unique = [c for c in candidates if not (c.code in seen or seen.add(c.code))]

        # Scan the whole (large) pool cheaply on the Nutri-Score + NOVA the search already
        # returned, so a healthier option buried deep in a popular category still gets seen.
        # Keep only candidates whose best-case (additive-free) upper bound beats the current
        # score, rank them best-bound first, and fully fetch just the top ``max_fetch``. The
        # bound never prunes a genuine improvement (real additives can only lower a score),
        # and capping the fetch keeps the product-endpoint fan-out small enough to dodge the
        # rate limit no matter how big the pool or how low the current score.
        beatable = []
        for c in unique:
            ub = _upper_bound(engine, c)
            if ub is not None and ub > current_score:
                beatable.append((ub, c.code))
        beatable.sort(key=lambda t: (-t[0], t[1]))
        to_fetch = [code for _, code in beatable[:max_fetch]]

        ranked: list[tuple[int, Alternative]] = []
        for p in await _fetch_many(off_client, to_fetch):
            if p.nova_group is None or p.nutriscore_grade is None:
                continue  # don't recommend products with missing data
            if not p.name or p.name == "Unknown product":
                continue  # never suggest a nameless product (off_client's missing-name sentinel)
            if tag not in _specific_tags(p.categories):
                continue  # must be the same KIND at this level — not a looser sibling
            result = engine.score(p)
            rank = uncapped_overall(result)
            if rank > current_score:
                display = weighted_overall(result)
                reason = _reason(product, current_dims, p, result.dimensions)
                ranked.append((rank, Alternative(p.off_id, p.name, p.brand, p.image_url, display, _band(display), reason)))

        if ranked:
            # Tightest non-empty level wins: show only its matches, best first (ties broken
            # by off_id for a stable order across loads). Looser levels never contribute.
            ranked.sort(key=lambda t: (-t[0], t[1].off_id))
            return [a for _, a in ranked][:max_results]
        # Nothing healthier at this level -> broaden to the next (looser) reasonable level.

    return []


# Categories so broad they mix unrelated product KINDS. These are never searched
# for alternatives, AND never count as the "same kind" link between two products:
# sharing only one of these (e.g. both are "snacks", both "confectioneries") does
# not make a cracker a valid alternative to chewing gum. Broadening into these is
# what surfaced juice/tea/yogurt for a cola, and biscuits/chocolate for gum.
_TOO_GENERIC_TAGS = frozenset({
    # Top-level / near-top groupings.
    "en:foods",
    "en:groceries",
    "en:beverages",
    "en:beverages-and-beverages-preparations",
    "en:plant-based-foods",
    "en:plant-based-foods-and-beverages",
    "en:dairies",
    "en:fats",
    "en:meats",
    "en:frozen-foods",
    "en:canned-foods",
    "en:fermented-foods",
    "en:fermented-milk-products",
    # Mid-level "snack / occasion" groupings that mix fundamentally different
    # kinds of product (the gum-vs-crackers failure lived here).
    "en:snacks",
    "en:sweet-snacks",
    "en:salty-snacks",
    "en:sugary-snacks",
    "en:confectioneries",
    "en:candies",
    "en:desserts",
    "en:breakfasts",
    "en:meals",
    "en:prepared-meals",
    "en:microwave-meals",
    "en:plant-based-meals",
    "en:cereals-and-potatoes",
    "en:cereals-and-their-products",
    # "Bars" spans cereal bars, chocolate bars and protein bars — too mixed to
    # establish same-kind on its own (real pairs share e.g. en:cereal-bars).
    "en:bars",
    # Cross-cutting beverage groupings defined by a *property* (carbonation,
    # sweetness, temperature) or by *negation* (non-alcoholic) rather than by kind.
    # Cola, tonic, sparkling water, iced tea and energy drinks all share several of
    # these, so they let unrelated drinks pose as the same kind — sparkling water
    # matched Pepsi on en:carbonated-drinks alone. Real kinds (en:colas, en:sodas,
    # en:diet-sodas, en:energy-drinks, en:iced-teas, …) are unaffected. All verified
    # present in the OFF categories taxonomy.
    "en:carbonated-drinks",
    "en:sweetened-beverages",
    "en:non-alcoholic-beverages",
    "en:artificially-sweetened-beverages",
    "en:diet-beverages",
    "en:hot-beverages",
    "en:flavoured-drinks",
    "en:plant-based-beverages",
})

# A canonical OFF category tag is an ``en:`` prefix followed by a lowercase,
# hyphenated ASCII slug. OFF also carries untranslated tags like
# ``en:Pâtes à tartiner`` (capitals/spaces/accents) that don't exist in the search
# index — those must be rejected so they don't waste search levels.
_CANONICAL_EN_TAG = re.compile(r"^en:[a-z0-9-]+$")


def _specific_tags(categories: list[str]) -> set[str]:
    """The canonical ``en:`` category tags specific enough to establish that two
    products are the *same kind* — i.e. excluding the broad ``_TOO_GENERIC_TAGS``
    groupings. Two products sharing at least one of these are genuinely comparable;
    sharing only a grouping like ``en:snacks`` is not enough."""
    return {c for c in categories
            if _CANONICAL_EN_TAG.match(c) and c not in _TOO_GENERIC_TAGS}


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
