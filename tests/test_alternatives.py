import httpx
import pytest
import respx

from app.additive_db import AdditiveDB
from app.alternatives import _ordered_category_tags, find_better_alternatives
from app.config import Settings
from app.models import NormalisedProduct
from app.off_client import OFFClient
from app.scoring.additive_scorer import AdditiveScorer
from app.scoring.food_engine import FoodScoringEngine

SEARCH_URL = "https://search.openfoodfacts.org/search"
PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"


@pytest.fixture
def engine(tmp_path):
    t = tmp_path / "taxonomy.json"
    c = tmp_path / "curated.yaml"
    t.write_text("[]")
    c.write_text("{}")
    return FoodScoringEngine(AdditiveScorer(AdditiveDB(t, c)))


@pytest.fixture
def client():
    return OFFClient(Settings(off_user_agent="TestApp/1.0", off_request_timeout=5.0, off_cache_ttl=300,
                              off_max_retries=2, off_retry_backoff=0.0))


def _current(categories, off_id="cur", nutri="C", nova=2):
    return NormalisedProduct(
        off_id=off_id, name="Current", brand="B",
        nutriscore_grade=nutri, nova_group=nova, additives=[],
        ingredients_text=None, image_url=None,
        raw_off_url="https://world.openfoodfacts.org/product/cur/",
        categories=categories,
    )


def _hit(code, grade=None, nova=None):
    """A category-search hit carrying the Nutri-Score + NOVA the pre-filter reads."""
    return {"code": code, "nutriscore_grade": grade, "nova_group": nova}


def _mock_product(code, grade, nova):
    """Register a candidate product. Grade/nova map to a known overall score."""
    respx.get(PRODUCT_URL.format(code=code)).mock(return_value=httpx.Response(200, json={"product": {
        "product_name": f"Product {code}", "brands": "Brand",
        "nutriscore_grade": grade, "nova_group": nova,
        "additives_tags": [], "image_url": f"http://img/{code}.jpg",
    }}))


@respx.mock
async def test_returns_only_better_sorted_capped_and_excludes_current(engine, client):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("cur", "c", 2), _hit("a", "a", 1), _hit("b", "a", 2), _hit("c", "b", 1),
        _hit("d", "b", 2), _hit("e", "c", 1), _hit("f", "c", 2), _hit("g", "d", 2),
    ]}))
    _mock_product("a", "a", 1)   # 100
    _mock_product("b", "a", 2)   # 95
    _mock_product("c", "b", 1)   # 90
    _mock_product("d", "b", 2)   # 85
    _mock_product("e", "c", 1)   # 80  (better, but trimmed by cap of 4)
    _mock_product("f", "c", 2)   # 75  (equal to current — excluded)
    _mock_product("g", "d", 2)   # 65  (worse — excluded)
    _mock_product("cur", "c", 2)  # the current product itself
    alts = await find_better_alternatives(client, engine, _current(["en:spreads", "en:chocolate-spreads"]), current_score=75)
    await client.aclose()
    assert [a.off_id for a in alts] == ["a", "b", "c", "d"]
    assert [a.score for a in alts] == [100, 95, 90, 85]
    assert "cur" not in [a.off_id for a in alts]
    assert alts[0].band == "good" and alts[0].image_url == "http://img/a.jpg"


@respx.mock
async def test_broadens_when_specific_category_too_sparse(engine, client):
    def search_handler(request):
        q = request.url.params.get("q")
        if "chocolate-spreads" in q:
            return httpx.Response(200, json={"hits": [_hit("x1", "a", 1)]})
        return httpx.Response(200, json={"hits": [_hit("x1", "a", 1), _hit("x2", "b", 2), _hit("x3", "a", 2)]})

    route = respx.get(SEARCH_URL).mock(side_effect=search_handler)
    _mock_product("x1", "a", 1)  # 100
    _mock_product("x2", "b", 2)  # 85
    _mock_product("x3", "a", 2)  # 95
    alts = await find_better_alternatives(client, engine, _current(["en:spreads", "en:chocolate-spreads"]), current_score=75)
    await client.aclose()
    # Most-specific level found only 1 better → broadened to the parent category.
    assert route.call_count == 2
    assert [a.score for a in alts] == [100, 95, 85]


@respx.mock
async def test_no_better_alternatives_returns_empty(engine, client):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [_hit("p1", "a", 1)]}))
    _mock_product("p1", "a", 1)  # 100, equal to current — not strictly better
    alts = await find_better_alternatives(client, engine, _current(["en:spreads", "en:chocolate-spreads"]), current_score=100)
    await client.aclose()
    assert alts == []


@respx.mock
async def test_failing_candidate_fetch_does_not_break_batch(engine, client):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("good", "a", 1), _hit("bad", "a", 1), _hit("good2", "b", 2),
    ]}))
    _mock_product("good", "a", 1)   # 100
    _mock_product("good2", "b", 2)  # 85
    respx.get(PRODUCT_URL.format(code="bad")).mock(return_value=httpx.Response(500))
    alts = await find_better_alternatives(client, engine, _current(["en:chocolate-spreads"]), current_score=70)
    await client.aclose()
    assert [a.off_id for a in alts] == ["good", "good2"]


@respx.mock
async def test_ranks_on_uncapped_score_so_cap_does_not_flatten(engine, client):
    """Regression: a NOVA-4 product's category neighbours are all NOVA-4 too, so the
    cap pins every displayed score to 35 — a 35-way tie that returned nothing.
    Ranking must use the uncapped underlying score so gradation survives, while the
    *displayed* score stays capped."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("cbet", "c", 4), _hit("dbet", "d", 4), _hit("etie", "e", 4),
    ]}))
    _mock_product("cbet", "c", 4)  # capped 35, uncapped 60  (better)
    _mock_product("dbet", "d", 4)  # capped 35, uncapped 50  (better)
    _mock_product("etie", "e", 4)  # capped 35, uncapped 40  (ties current — excluded)
    # Current product E/NOVA4: capped 35, uncapped 40.
    alts = await find_better_alternatives(client, engine, _current(["en:chocolate-spreads"]), current_score=40)
    await client.aclose()
    # Both better neighbours surface, ordered by the uncapped score (60 before 50)...
    assert [a.off_id for a in alts] == ["cbet", "dbet"]
    # ...but the score shown to the user is still the capped 35.
    assert [a.score for a in alts] == [35, 35]


@respx.mock
async def test_excludes_candidates_missing_nova_or_nutrition(engine, client):
    """A candidate missing NOVA or Nutri-Score data must not be recommended — it only
    looks good because there's no data to penalise it."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("nonova", grade="a"), _hit("nonutri", nova=1), _hit("good", "a", 1),
    ]}))
    # Missing NOVA (nutri present).
    respx.get(PRODUCT_URL.format(code="nonova")).mock(return_value=httpx.Response(200, json={"product": {
        "product_name": "No NOVA", "brands": "X", "nutriscore_grade": "a",
        "additives_tags": [], "image_url": None, "categories_tags": ["en:chocolate-spreads"]}}))
    # Missing Nutri-Score (nova present).
    respx.get(PRODUCT_URL.format(code="nonutri")).mock(return_value=httpx.Response(200, json={"product": {
        "product_name": "No Nutri", "brands": "X", "nova_group": 1,
        "additives_tags": [], "image_url": None, "categories_tags": ["en:chocolate-spreads"]}}))
    _mock_product("good", "a", 1)  # complete data, score 100
    alts = await find_better_alternatives(client, engine, _current(["en:chocolate-spreads"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["good"]


@respx.mock
async def test_prefilters_unbeatable_candidates_without_fetching(engine, client):
    """A candidate that can't beat the current score even with a perfect additive
    profile is pruned from its Nutri-Score + NOVA alone — its product endpoint is
    never hit. This keeps the fan-out small enough to dodge the OFF rate limit."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("good", "a", 1),   # upper bound 100 -> fetched
        _hit("poor", "e", 4),   # upper bound 40 -> pruned, never fetched
    ]}))
    _mock_product("good", "a", 1)
    poor_route = respx.get(PRODUCT_URL.format(code="poor")).mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Poor", "nutriscore_grade": "e", "nova_group": 4,
            "additives_tags": [], "categories_tags": ["en:x"]}}))
    alts = await find_better_alternatives(client, engine, _current(["en:x"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["good"]
    assert poor_route.call_count == 0


@respx.mock
async def test_reason_reports_improved_nutrition(engine, client):
    """Only nutrition differs → the card explains the nutrition improvement."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [_hit("c1", "c", 2)]}))
    _mock_product("c1", "c", 2)  # better Nutri-Score, same processing
    alts = await find_better_alternatives(
        client, engine, _current(["en:x"], nutri="E", nova=2), current_score=0)
    await client.aclose()
    assert alts[0].reason == "Better nutrition (Nutri-Score C vs E)"


@respx.mock
async def test_reason_reports_less_processed(engine, client):
    """Only processing differs → the card explains the processing improvement."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [_hit("c1", "c", 2)]}))
    _mock_product("c1", "c", 2)  # same Nutri-Score, less processed
    alts = await find_better_alternatives(
        client, engine, _current(["en:x"], nutri="C", nova=4), current_score=0)
    await client.aclose()
    assert alts[0].reason == "Less processed (NOVA 2 vs 4)"


@respx.mock
async def test_equal_scoring_alternatives_ordered_deterministically(engine, client):
    """Among candidates that tie on the ranking score, order by off_id so repeated
    loads return the same order instead of whatever order fetches happened to finish."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("zzz", "a", 1), _hit("aaa", "a", 1), _hit("mmm", "a", 1),
    ]}))
    _mock_product("zzz", "a", 1)  # 100
    _mock_product("aaa", "a", 1)  # 100 — tie
    _mock_product("mmm", "a", 1)  # 100 — tie
    alts = await find_better_alternatives(client, engine, _current(["en:x"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["aaa", "mmm", "zzz"]


@respx.mock
async def test_no_categories_returns_empty_without_searching(engine, client):
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": []}))
    alts = await find_better_alternatives(client, engine, _current([]), current_score=50)
    await client.aclose()
    assert alts == []
    assert route.call_count == 0


def test_ordered_category_tags_most_specific_first():
    cats = [
        "en:breakfasts", "en:spreads", "en:sweet-spreads",
        "fr:pates-a-tartiner", "en:chocolate-spreads",
        "en:cocoa-and-hazelnuts-spreads",
    ]
    assert _ordered_category_tags(cats) == [
        "en:cocoa-and-hazelnuts-spreads",
        "en:chocolate-spreads",
        "en:sweet-spreads",
        "en:spreads",
        "en:breakfasts",
    ]


def test_ordered_category_tags_drops_too_generic_categories():
    """Generic roots that mix unrelated product types (drinks with food) must never be
    searched — they are what surfaced juice/tea/yogurt as 'alternatives' to a cola."""
    cats = [
        "en:beverages-and-beverages-preparations", "en:beverages",
        "en:carbonated-drinks", "en:sodas", "en:colas",
    ]
    assert _ordered_category_tags(cats) == ["en:colas", "en:sodas", "en:carbonated-drinks"]


@respx.mock
async def test_rate_limited_specific_search_stops_instead_of_broadening(engine, client):
    """A rate-limited (or failed) category search must NOT silently broaden into the
    parent category — that's how a cola ended up next to juice. Honest empty instead."""
    broadened = False

    def handler(request):
        nonlocal broadened
        q = request.url.params.get("q")
        if "chocolate-spreads" in q:
            return httpx.Response(429)  # persistent rate-limit on the specific tag
        broadened = True
        return httpx.Response(200, json={"hits": [{"code": "junk"}]})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("junk", "a", 1)  # would score 100, falsely "better"
    alts = await find_better_alternatives(
        client, engine, _current(["en:spreads", "en:chocolate-spreads"]), current_score=50)
    await client.aclose()
    assert alts == []
    assert broadened is False


@respx.mock
async def test_never_broadens_into_generic_category(engine, client):
    """When the specific tag is sparse, broadening must skip generic roots like
    en:beverages entirely rather than mixing in unrelated drinks."""
    searched = []

    def handler(request):
        q = request.url.params.get("q")
        searched.append(q)
        if "colas" in q:
            return httpx.Response(200, json={"hits": [_hit("c1", "a", 1)]})  # only 1 better
        return httpx.Response(200, json={"hits": [_hit("j1", "a", 1), _hit("j2", "a", 1)]})  # junk

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("c1", "a", 1)
    _mock_product("j1", "a", 1)
    _mock_product("j2", "a", 1)
    alts = await find_better_alternatives(
        client, engine, _current(["en:beverages", "en:colas"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["c1"]
    assert not any("beverages" in q for q in searched)


async def test_fetch_many_limits_concurrency():
    """The candidate fetch must cap concurrency so it can't burst-trip the OFF rate limit."""
    import asyncio

    from app.alternatives import _fetch_many

    state = {"inflight": 0, "max": 0}

    class FakeClient:
        async def fetch_product(self, code):
            state["inflight"] += 1
            state["max"] = max(state["max"], state["inflight"])
            await asyncio.sleep(0.01)
            state["inflight"] -= 1
            return NormalisedProduct(
                off_id=code, name="P", brand=None, nutriscore_grade="A", nova_group=1,
                additives=[], ingredients_text=None, image_url=None, raw_off_url="")

    res = await _fetch_many(FakeClient(), [str(i) for i in range(12)])
    assert len(res) == 12
    assert state["max"] <= 4


def test_ordered_category_tags_drops_malformed_non_canonical_tags():
    """OFF carries untranslated en:-prefixed tags with capitals/spaces/accents
    (e.g. 'en:Pâtes à tartiner'). They don't exist in the search index, so if they
    occupy the most-specific slots they waste every search level and the product
    gets no alternatives. Drop them; keep the real canonical slugs below."""
    cats = [
        "en:breakfasts", "en:spreads", "en:sweet-spreads",
        "en:confectionary-based-spreads",
        "en:Produits à tartiner", "en:Produits à tartiner sucrés",
        "en:Pâtes à tartiner",
    ]
    assert _ordered_category_tags(cats) == [
        "en:confectionary-based-spreads", "en:sweet-spreads", "en:spreads", "en:breakfasts"]


def test_ordered_category_tags_ignores_non_english_tags():
    assert _ordered_category_tags(["fr:bonbons", "de:bonbons"]) == []


def test_ordered_category_tags_empty():
    assert _ordered_category_tags([]) == []
