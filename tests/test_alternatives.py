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


def _current(categories, off_id="cur", nutri="C", nova=2, countries=None):
    return NormalisedProduct(
        off_id=off_id, name="Current", brand="B",
        nutriscore_grade=nutri, nova_group=nova, additives=[],
        ingredients_text=None, image_url=None,
        raw_off_url="https://world.openfoodfacts.org/product/cur/",
        categories=categories,
        countries_tags=countries or [],
    )


def _hit(code, grade=None, nova=None):
    """A category-search hit carrying the Nutri-Score + NOVA the pre-filter reads."""
    return {"code": code, "nutriscore_grade": grade, "nova_group": nova}


def _mock_product(code, grade, nova, cats=("en:chocolate-spreads",)):
    """Register a candidate product. Grade/nova map to a known overall score.

    ``cats`` are the candidate's category tags — by default the same specific
    category most tests' current product carries, so the same-kind filter keeps
    it (a candidate found under a category genuinely belongs to it)."""
    return respx.get(PRODUCT_URL.format(code=code)).mock(return_value=httpx.Response(200, json={"product": {
        "product_name": f"Product {code}", "brands": "Brand",
        "nutriscore_grade": grade, "nova_group": nova,
        "additives_tags": [], "image_url": f"http://img/{code}.jpg",
        "categories_tags": list(cats),
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
async def test_tightest_level_with_one_match_shows_only_it_no_broaden(engine, client):
    """One healthier match at the tightest level is enough — show only it and do NOT
    broaden to a looser level (broadening on <2 is how a sibling soda reached a cola)."""
    searched = []

    def search_handler(request):
        q = request.url.params.get("q")
        searched.append(q)
        if "chocolate-spreads" in q:
            return httpx.Response(200, json={"hits": [_hit("x1", "a", 1)]})
        return httpx.Response(200, json={"hits": [_hit("x2", "a", 1), _hit("x3", "a", 1)]})

    respx.get(SEARCH_URL).mock(side_effect=search_handler)
    _mock_product("x1", "a", 1)  # 100, in the tightest level
    _mock_product("x2", "a", 1)
    _mock_product("x3", "a", 1)
    alts = await find_better_alternatives(
        client, engine, _current(["en:spreads", "en:chocolate-spreads"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["x1"]               # only the tightest-level match
    assert all("chocolate-spreads" in q for q in searched)  # never broadened to en:spreads


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
    alts = await find_better_alternatives(client, engine, _current(["en:chocolate-spreads"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["good"]
    assert poor_route.call_count == 0


@respx.mock
async def test_searches_a_large_candidate_pool_by_default(engine, client):
    """Healthier options often sit deep in a category behind more-popular unhealthy ones,
    so the candidate search must pull a large pool, not a dozen — this is the aloe-vera
    starvation, where the healthier aloe drinks fell outside the top-12 slice."""
    captured = {}

    def handler(request):
        captured["page_size"] = request.url.params.get("page_size")
        return httpx.Response(200, json={"hits": [_hit("x", "a", 1)]})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("x", "a", 1)
    await find_better_alternatives(
        client, engine, _current(["en:chocolate-spreads"]), current_score=50)
    await client.aclose()
    assert captured["page_size"] == "100"


@respx.mock
async def test_caps_full_fetches_to_top_upper_bound_candidates(engine, client):
    """A large pool must not become a large fan-out: only the most promising candidates
    (highest Nutri-Score + NOVA upper bound) are fully fetched, bounding product-endpoint
    calls so a 100-item pool can't trip the OFF rate limit. The pre-filter already gives a
    cheap upper bound per candidate; rank by it and fetch only the top ``max_fetch``."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("u100", "a", 1), _hit("u90", "b", 1), _hit("u80", "c", 1), _hit("u75", "c", 2),
    ]}))
    routes = {
        "u100": _mock_product("u100", "a", 1),  # upper bound 100
        "u90": _mock_product("u90", "b", 1),    # upper bound 90
        "u80": _mock_product("u80", "c", 1),    # upper bound 80
        "u75": _mock_product("u75", "c", 2),    # upper bound 75
    }
    alts = await find_better_alternatives(
        client, engine, _current(["en:chocolate-spreads"]), current_score=0, max_fetch=2)
    await client.aclose()
    # Only the two highest-upper-bound candidates are fetched at all...
    assert routes["u100"].call_count == 1
    assert routes["u90"].call_count == 1
    assert routes["u80"].call_count == 0
    assert routes["u75"].call_count == 0
    # ...and they are exactly what's shown, best first.
    assert [a.off_id for a in alts] == ["u100", "u90"]


@respx.mock
async def test_excludes_alternative_with_missing_name(engine, client):
    """Never suggest a nameless product. A candidate whose name is missing — OFF returns
    the 'Unknown product' placeholder — is dropped even when it scores better."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("named", "a", 1), _hit("noname", "a", 1),
    ]}))
    _mock_product("named", "a", 1)
    # No product_name in the OFF payload -> _normalise yields the "Unknown product" sentinel.
    respx.get(PRODUCT_URL.format(code="noname")).mock(return_value=httpx.Response(200, json={"product": {
        "nutriscore_grade": "a", "nova_group": 1, "additives_tags": [],
        "image_url": "http://img/noname.jpg", "categories_tags": ["en:chocolate-spreads"]}}))
    alts = await find_better_alternatives(
        client, engine, _current(["en:chocolate-spreads"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["named"]
    assert all(a.name and a.name != "Unknown product" for a in alts)


@respx.mock
async def test_region_filter_prefers_same_country(engine, client):
    """Option A: alternatives are filtered to the viewed product's country, so a UK product
    isn't offered a cola it can't buy. When the in-country search yields a healthier
    same-kind match, that's what's shown — the search carries the country clause."""
    searched = []

    def handler(request):
        q = request.url.params.get("q")
        searched.append(q)
        if "united-kingdom" in q:
            return httpx.Response(200, json={"hits": [_hit("uk1", "a", 1)]})
        return httpx.Response(200, json={"hits": [_hit("foreign", "a", 1)]})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("uk1", "a", 1)
    _mock_product("foreign", "a", 1)
    cur = _current(["en:chocolate-spreads"], countries=["en:united-kingdom"])
    alts = await find_better_alternatives(client, engine, cur, current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["uk1"]          # the in-country match, not the foreign one
    assert "united-kingdom" in searched[0]              # in-country search tried first


@respx.mock
async def test_region_falls_back_to_unfiltered_when_no_local_match(engine, client):
    """The UK-aloe case: no HEALTHIER in-country option, so fall back to an unfiltered
    search at the same level rather than showing nothing — a foreign same-kind product is
    better than an empty section."""
    searched = []

    def handler(request):
        q = request.url.params.get("q")
        searched.append(q)
        if "united-kingdom" in q:
            return httpx.Response(200, json={"hits": []})   # nothing healthier in-country
        return httpx.Response(200, json={"hits": [_hit("foreign", "a", 1)]})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("foreign", "a", 1)
    cur = _current(["en:chocolate-spreads"], countries=["en:united-kingdom"])
    alts = await find_better_alternatives(client, engine, cur, current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["foreign"]        # honest cross-border fallback
    assert "united-kingdom" in searched[0]                # in-country tried first
    assert any("united-kingdom" not in q for q in searched)  # then unfiltered fallback


@respx.mock
async def test_reason_reports_improved_nutrition(engine, client):
    """Only nutrition differs → the card explains the nutrition improvement."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [_hit("c1", "c", 2)]}))
    _mock_product("c1", "c", 2)  # better Nutri-Score, same processing
    alts = await find_better_alternatives(
        client, engine, _current(["en:chocolate-spreads"], nutri="E", nova=2), current_score=0)
    await client.aclose()
    assert alts[0].reason == "Better nutrition (Nutri-Score C vs E)"


@respx.mock
async def test_reason_reports_less_processed(engine, client):
    """Only processing differs → the card explains the processing improvement."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [_hit("c1", "c", 2)]}))
    _mock_product("c1", "c", 2)  # same Nutri-Score, less processed
    alts = await find_better_alternatives(
        client, engine, _current(["en:chocolate-spreads"], nutri="C", nova=4), current_score=0)
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
    alts = await find_better_alternatives(client, engine, _current(["en:chocolate-spreads"]), current_score=50)
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
    # en:breakfasts is a cross-kind grouping (cereals + spreads + pastries), so it's
    # dropped; the specific spread tags remain, most-specific first.
    assert _ordered_category_tags(cats) == [
        "en:cocoa-and-hazelnuts-spreads",
        "en:chocolate-spreads",
        "en:sweet-spreads",
        "en:spreads",
    ]


def test_ordered_category_tags_drops_too_generic_categories():
    """Generic roots that mix unrelated product types (drinks with food) must never be
    searched — they are what surfaced juice/tea/yogurt as 'alternatives' to a cola.

    en:carbonated-drinks is also dropped: it's a cross-cutting *property* grouping
    (cola, tonic, sparkling water, energy drinks are all 'carbonated') and so cannot
    define a same kind. Only the genuine kind tags en:colas/en:sodas survive."""
    cats = [
        "en:beverages-and-beverages-preparations", "en:beverages",
        "en:carbonated-drinks", "en:sodas", "en:colas",
    ]
    assert _ordered_category_tags(cats) == ["en:colas", "en:sodas"]


def test_ordered_category_tags_drops_beverage_property_groupings():
    """Property/negation beverage groupings (carbonated / sweetened / non-alcoholic)
    span fundamentally different drink kinds, so they must never be searched or anchor
    a match — only en:colas/en:sodas are real kinds here."""
    cats = [
        "en:beverages", "en:carbonated-drinks", "en:non-alcoholic-beverages",
        "en:sodas", "en:colas", "en:sweetened-beverages",
    ]
    assert _ordered_category_tags(cats) == ["en:colas", "en:sodas"]


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
    _mock_product("c1", "a", 1, cats=["en:colas"])
    _mock_product("j1", "a", 1)
    _mock_product("j2", "a", 1)
    alts = await find_better_alternatives(
        client, engine, _current(["en:beverages", "en:colas"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["c1"]
    assert not any("beverages" in q for q in searched)


@respx.mock
async def test_excludes_better_candidate_of_a_different_kind(engine, client):
    """A higher-scoring product that shares only a broad grouping (e.g. en:sweet-snacks)
    and NOT a specific category must be rejected. This is the gum-vs-biscuits bug:
    a biscuit is not a valid alternative to chewing gum just because both are 'snacks'."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("gum2", "a", 1), _hit("biscuit", "a", 1),
    ]}))
    _mock_product("gum2", "a", 1, cats=["en:chewing-gum", "en:sweet-snacks"])       # same kind
    _mock_product("biscuit", "a", 1, cats=["en:biscuits", "en:sweet-snacks"])       # different kind
    alts = await find_better_alternatives(
        client, engine, _current(["en:chewing-gum", "en:sweet-snacks"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["gum2"]


@respx.mock
async def test_niche_category_with_no_same_kind_options_returns_empty(engine, client):
    """The honest empty state: when the only better products are a different kind,
    show nothing rather than broadening into unrelated foods."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("biscuit", "a", 1), _hit("chocolate", "a", 1),
    ]}))
    _mock_product("biscuit", "a", 1, cats=["en:biscuits", "en:sweet-snacks"])
    _mock_product("chocolate", "a", 1, cats=["en:dark-chocolates", "en:confectioneries"])
    alts = await find_better_alternatives(
        client, engine, _current(["en:chewing-gum", "en:confectioneries"]), current_score=50)
    await client.aclose()
    assert alts == []


@respx.mock
async def test_only_generic_categories_returns_empty_without_searching(engine, client):
    """If a product carries nothing more specific than grouping tags, there's no way to
    find the same kind — return empty and don't even search."""
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": []}))
    alts = await find_better_alternatives(
        client, engine, _current(["en:snacks", "en:sweet-snacks", "en:confectioneries"]), current_score=50)
    await client.aclose()
    assert alts == []
    assert route.call_count == 0


@respx.mock
async def test_pepsi_shows_only_colas_when_a_better_cola_exists(engine, client):
    """The Pepsi case: a healthier cola (Coke Zero) exists at the tightest level (en:colas),
    so ONLY colas are shown. The blood-orange spritz / Fanta (sodas, not colas) and the
    sparkling water / energy drink (property-only) never appear, and the search never even
    broadens to en:sodas."""
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("cokezero", "a", 1), _hit("fanta", "a", 1), _hit("spritz", "a", 1),
        _hit("water", "a", 1), _hit("energy", "a", 1),
    ]}))
    _mock_product("cokezero", "a", 1,
                  cats=["en:beverages", "en:carbonated-drinks", "en:sodas", "en:colas", "en:diet-sodas"])
    _mock_product("fanta", "a", 1,
                  cats=["en:beverages", "en:carbonated-drinks", "en:sodas", "en:orange-sodas"])
    _mock_product("spritz", "a", 1,
                  cats=["en:beverages", "en:carbonated-drinks", "en:sodas", "en:sweetened-beverages"])
    _mock_product("water", "a", 1,
                  cats=["en:beverages", "en:carbonated-drinks", "en:carbonated-waters", "en:waters"])
    _mock_product("energy", "a", 1,
                  cats=["en:beverages", "en:sweetened-beverages", "en:carbonated-drinks", "en:energy-drinks"])
    pepsi = _current(
        ["en:beverages-and-beverages-preparations", "en:beverages", "en:carbonated-drinks",
         "en:non-alcoholic-beverages", "en:sodas", "en:colas", "en:sweetened-beverages"],
        nutri="E", nova=4)
    alts = await find_better_alternatives(client, engine, pepsi, current_score=40)
    await client.aclose()
    ids = [a.off_id for a in alts]
    assert ids == ["cokezero"]          # only the cola
    assert route.call_count == 1        # returned at en:colas, never broadened to en:sodas
    for absent in ("spritz", "fanta", "water", "energy"):
        assert absent not in ids


@respx.mock
async def test_pepsi_falls_back_to_better_soda_only_when_no_better_cola(engine, client):
    """If the tightest level (en:colas) has no HEALTHIER cola — only a worse one — broaden
    one level to en:sodas and offer the genuinely healthier sodas instead of nothing."""
    searched = []

    def handler(request):
        q = request.url.params.get("q")
        searched.append(q)
        if "colas" in q:
            return httpx.Response(200, json={"hits": [_hit("cola_e", "e", 4)]})  # a cola, but worse
        if "sodas" in q:
            return httpx.Response(200, json={"hits": [_hit("fanta", "a", 1), _hit("spritz", "a", 1)]})
        return httpx.Response(200, json={"hits": []})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("cola_e", "e", 4, cats=["en:colas", "en:sodas"])       # not healthier -> pruned
    _mock_product("fanta", "a", 1, cats=["en:sodas", "en:orange-sodas"])
    _mock_product("spritz", "a", 1, cats=["en:sodas", "en:sweetened-beverages"])
    pepsi = _current(["en:beverages", "en:carbonated-drinks", "en:sodas", "en:colas"],
                     nutri="E", nova=4)
    alts = await find_better_alternatives(client, engine, pepsi, current_score=40)
    await client.aclose()
    ids = [a.off_id for a in alts]
    assert ids == ["fanta", "spritz"]                   # honest soda fallback (tie -> off_id order)
    assert searched[0] == 'categories_tags:"en:colas"'  # tightest tried first
    assert any("sodas" in q for q in searched)          # broadened only after colas had no healthier cola


@respx.mock
async def test_narrow_category_falls_back_to_close_sibling(engine, client):
    """A cocoa-hazelnut spread with no healthier option in its exact niche broadens to the
    parent kind (chocolate spreads) and offers a close sibling — not an empty section."""
    searched = []

    def handler(request):
        q = request.url.params.get("q")
        searched.append(q)
        if "cocoa-and-hazelnuts-spreads" in q:
            return httpx.Response(200, json={"hits": []})           # nothing healthier in the niche
        if "chocolate-spreads" in q:
            return httpx.Response(200, json={"hits": [_hit("sibling", "a", 1)]})
        return httpx.Response(200, json={"hits": []})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("sibling", "a", 1, cats=["en:spreads", "en:sweet-spreads", "en:chocolate-spreads"])
    current = _current(
        ["en:spreads", "en:sweet-spreads", "en:chocolate-spreads", "en:cocoa-and-hazelnuts-spreads"],
        nutri="C", nova=2)
    alts = await find_better_alternatives(client, engine, current, current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["sibling"]                   # a close sibling, not empty
    assert searched[0] == 'categories_tags:"en:cocoa-and-hazelnuts-spreads"'  # tightest first
    assert any("chocolate-spreads" in q for q in searched)          # broadened one level


@respx.mock
async def test_shows_at_least_one_when_a_healthier_option_exists_somewhere(engine, client):
    """The non-empty guarantee: the tightest level is barren but a healthier option exists
    at a broader (still specific, non-generic) level — surface it rather than nothing."""
    def handler(request):
        q = request.url.params.get("q")
        if "chocolate-spreads" in q:
            return httpx.Response(200, json={"hits": []})
        return httpx.Response(200, json={"hits": [_hit("betterspread", "a", 1)]})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("betterspread", "a", 1, cats=["en:spreads"])
    alts = await find_better_alternatives(
        client, engine, _current(["en:spreads", "en:chocolate-spreads"]), current_score=50)
    await client.aclose()
    assert len(alts) >= 1
    assert alts[0].off_id == "betterspread"


@respx.mock
async def test_only_property_grouping_tags_returns_empty_without_searching(engine, client):
    """Precision over recall: a drink tagged only with cross-cutting property/negation
    groupings (no real kind tag) has no same-kind anchor, so it returns the honest empty
    state rather than matching unrelated drinks — and never even searches."""
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": []}))
    alts = await find_better_alternatives(
        client, engine,
        _current(["en:beverages", "en:carbonated-drinks", "en:non-alcoholic-beverages",
                  "en:sweetened-beverages"]),
        current_score=50)
    await client.aclose()
    assert alts == []
    assert route.call_count == 0


def test_ordered_category_tags_drops_snack_and_confectionery_groupings():
    """The grouping tags that mixed gum with biscuits/chocolate must never be searched."""
    cats = ["en:snacks", "en:sweet-snacks", "en:confectioneries", "en:chewing-gum"]
    assert _ordered_category_tags(cats) == ["en:chewing-gum"]


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
    # (en:breakfasts is also dropped now as a cross-kind grouping.)
    assert _ordered_category_tags(cats) == [
        "en:confectionary-based-spreads", "en:sweet-spreads", "en:spreads"]


def test_ordered_category_tags_ignores_non_english_tags():
    assert _ordered_category_tags(["fr:bonbons", "de:bonbons"]) == []


def test_ordered_category_tags_empty():
    assert _ordered_category_tags([]) == []
