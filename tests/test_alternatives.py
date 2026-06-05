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
    return OFFClient(Settings(off_user_agent="TestApp/1.0", off_request_timeout=5.0, off_cache_ttl=300))


def _current(categories, off_id="cur"):
    return NormalisedProduct(
        off_id=off_id, name="Current", brand="B",
        nutriscore_grade="C", nova_group=2, additives=[],
        ingredients_text=None, image_url=None,
        raw_off_url="https://world.openfoodfacts.org/product/cur/",
        categories=categories,
    )


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
        {"code": "cur"}, {"code": "a"}, {"code": "b"}, {"code": "c"},
        {"code": "d"}, {"code": "e"}, {"code": "f"}, {"code": "g"},
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
            return httpx.Response(200, json={"hits": [{"code": "x1"}]})
        return httpx.Response(200, json={"hits": [{"code": "x1"}, {"code": "x2"}, {"code": "x3"}]})

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
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [{"code": "p1"}]}))
    _mock_product("p1", "a", 1)  # 100, equal to current — not strictly better
    alts = await find_better_alternatives(client, engine, _current(["en:spreads", "en:chocolate-spreads"]), current_score=100)
    await client.aclose()
    assert alts == []


@respx.mock
async def test_failing_candidate_fetch_does_not_break_batch(engine, client):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        {"code": "good"}, {"code": "bad"}, {"code": "good2"},
    ]}))
    _mock_product("good", "a", 1)   # 100
    _mock_product("good2", "b", 2)  # 85
    respx.get(PRODUCT_URL.format(code="bad")).mock(return_value=httpx.Response(500))
    alts = await find_better_alternatives(client, engine, _current(["en:chocolate-spreads"]), current_score=70)
    await client.aclose()
    assert [a.off_id for a in alts] == ["good", "good2"]


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


def test_ordered_category_tags_ignores_non_english_tags():
    assert _ordered_category_tags(["fr:bonbons", "de:bonbons"]) == []


def test_ordered_category_tags_empty():
    assert _ordered_category_tags([]) == []
