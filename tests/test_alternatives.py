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


def _current(categories, off_id="cur", nutri="C", nova=2):
    return NormalisedProduct(
        off_id=off_id, name="Current", brand="B",
        nutriscore_grade=nutri, nova_group=nova, additives=[],
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
async def test_ranks_on_uncapped_score_so_cap_does_not_flatten(engine, client):
    """Regression: a NOVA-4 product's category neighbours are all NOVA-4 too, so the
    cap pins every displayed score to 35 — a 35-way tie that returned nothing.
    Ranking must use the uncapped underlying score so gradation survives, while the
    *displayed* score stays capped."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        {"code": "cbet"}, {"code": "dbet"}, {"code": "etie"},
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
        {"code": "nonova"}, {"code": "nonutri"}, {"code": "good"},
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
async def test_reason_reports_improved_nutrition(engine, client):
    """Only nutrition differs → the card explains the nutrition improvement."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [{"code": "c1"}]}))
    _mock_product("c1", "c", 2)  # better Nutri-Score, same processing
    alts = await find_better_alternatives(
        client, engine, _current(["en:x"], nutri="E", nova=2), current_score=0)
    await client.aclose()
    assert alts[0].reason == "Better nutrition (Nutri-Score C vs E)"


@respx.mock
async def test_reason_reports_less_processed(engine, client):
    """Only processing differs → the card explains the processing improvement."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [{"code": "c1"}]}))
    _mock_product("c1", "c", 2)  # same Nutri-Score, less processed
    alts = await find_better_alternatives(
        client, engine, _current(["en:x"], nutri="C", nova=4), current_score=0)
    await client.aclose()
    assert alts[0].reason == "Less processed (NOVA 2 vs 4)"


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
