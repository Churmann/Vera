import base64

import httpx
import pytest
import respx

from app.config import Settings
from app.models import OFFError
from app.off_client import OFFClient, _normalise


@pytest.fixture
def settings():
    # off_retry_backoff=0.0 keeps retry tests instant; off_max_retries=2 makes call counts deterministic.
    return Settings(off_user_agent="TestApp/1.0", off_request_timeout=5.0, off_cache_ttl=300,
                    off_max_retries=2, off_retry_backoff=0.0)


@respx.mock
async def test_search_returns_summaries(settings):
    respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={
            "hits": [{"code": "3017620422003", "product_name": "Nutella", "brands": ["Ferrero"], "image_url": None}]
        })
    )
    client = OFFClient(settings)
    results = await client.search("nutella")
    await client.aclose()
    assert len(results) == 1
    assert results[0].name == "Nutella"
    assert results[0].off_id == "3017620422003"
    assert results[0].brand == "Ferrero"


@respx.mock
async def test_search_skips_entries_without_name(settings):
    respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={
            "hits": [
                {"code": "123", "product_name": ""},
                {"code": "456", "product_name": "Good product", "brands": ["Brand"]},
            ]
        })
    )
    client = OFFClient(settings)
    results = await client.search("test")
    await client.aclose()
    assert len(results) == 1
    assert results[0].off_id == "456"


@respx.mock
async def test_search_raises_on_timeout(settings):
    respx.get("https://search.openfoodfacts.org/search").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    client = OFFClient(settings)
    with pytest.raises(OFFError) as exc:
        await client.search("nutella")
    await client.aclose()
    assert exc.value.kind == "timeout"


@respx.mock
async def test_search_raises_on_429(settings):
    respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(429)
    )
    client = OFFClient(settings)
    with pytest.raises(OFFError) as exc:
        await client.search("nutella")
    await client.aclose()
    assert exc.value.kind == "rate_limited"


@respx.mock
async def test_fetch_product_normalises_fields(settings):
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella", "brands": "Ferrero",
            "nutriscore_grade": "e", "nova_group": 4,
            "additives_tags": ["en:e322-lecithins", "en:e407-carrageenan"],
            "ingredients_text": "Sugar, palm oil", "image_url": None,
        }})
    )
    client = OFFClient(settings)
    product = await client.fetch_product("3017620422003")
    await client.aclose()
    assert product.nutriscore_grade == "E"
    assert product.nova_group == 4
    assert "e322" in product.additives
    assert "e407" in product.additives


@respx.mock
async def test_fetch_product_caches_result(settings):
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"product": {"product_name": "Nutella", "brands": "Ferrero"}})

    respx.get("https://world.openfoodfacts.org/api/v2/product/123.json").mock(side_effect=handler)
    client = OFFClient(settings)
    await client.fetch_product("123")
    await client.fetch_product("123")
    await client.aclose()
    assert call_count == 1


@respx.mock
async def test_fetch_product_raises_not_found(settings):
    respx.get("https://world.openfoodfacts.org/api/v2/product/999.json").mock(
        return_value=httpx.Response(404, json={"status": 0})
    )
    client = OFFClient(settings)
    with pytest.raises(OFFError) as exc:
        await client.fetch_product("999")
    await client.aclose()
    assert exc.value.kind == "not_found"


@respx.mock
async def test_fetch_product_collapses_additive_subtypes(settings):
    """e322i and e322ii are subtypes of e322 — collapse to base, deduplicate."""
    respx.get("https://world.openfoodfacts.org/api/v2/product/456.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Test Product",
            "additives_tags": [
                "en:e322-lecithins",
                "en:e322i-soya-lecithin",
                "en:e322ii-sunflower-lecithin",
            ],
        }})
    )
    client = OFFClient(settings)
    product = await client.fetch_product("456")
    await client.aclose()
    assert "e322" in product.additives
    assert "e322i" not in product.additives
    assert "e322ii" not in product.additives
    assert product.additives.count("e322") == 1


@respx.mock
async def test_fetch_product_preserves_letter_variant_additives(settings):
    """e160a (beta-carotene) is a distinct additive — do NOT collapse to e160."""
    respx.get("https://world.openfoodfacts.org/api/v2/product/789.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Test Product",
            "additives_tags": ["en:e160a-beta-carotene"],
        }})
    )
    client = OFFClient(settings)
    product = await client.fetch_product("789")
    await client.aclose()
    assert "e160a" in product.additives
    assert "e160" not in product.additives


@respx.mock
async def test_search_category_returns_candidates_with_scoring_fields(settings):
    route = respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={
            "hits": [
                {"code": "111", "nutriscore_grade": "a", "nova_group": 1},
                {"code": "222", "nutriscore_grade": "e", "nova_group": 4},
                {"code": "", "nutriscore_grade": "a"},  # no code -> skipped
            ]
        })
    )
    client = OFFClient(settings)
    cands = await client.search_category("en:chocolate-spreads", page_size=12)
    await client.aclose()
    assert [c.code for c in cands] == ["111", "222"]
    # Nutri-Score + NOVA are parsed so candidates can be pre-ranked without a fetch.
    assert cands[0].nutriscore_grade == "A" and cands[0].nova_group == 1
    assert cands[1].nutriscore_grade == "E" and cands[1].nova_group == 4
    sent = route.calls.last.request.url.params
    assert "categories_tags" in sent.get("q") and "en:chocolate-spreads" in sent.get("q")
    assert "nutriscore_grade" in sent.get("fields") and "nova_group" in sent.get("fields")


@respx.mock
async def test_search_category_sorts_by_nutriscore_to_surface_healthier_options(settings):
    """A bare category filter has no relevance signal, so OFF returns an arbitrary,
    varying page. Sorting by Nutri-Score (healthiest first) makes the set deterministic
    AND pulls the healthier options into the fetched slice — a popularity sort instead
    buried them behind the most-scanned, typically less-healthy mainstream products
    (the aloe-vera starvation)."""
    route = respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={"hits": [{"code": "111"}]})
    )
    client = OFFClient(settings)
    await client.search_category("en:colas")
    await client.aclose()
    assert route.calls.last.request.url.params.get("sort_by") == "nutriscore_score"


@respx.mock
async def test_search_category_filters_by_country_when_given(settings):
    """Option A region filter: when countries are supplied, the search constrains results to
    those markets via countries_tags so we never offer a product the user can't buy."""
    route = respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={"hits": []})
    )
    client = OFFClient(settings)
    await client.search_category("en:colas", countries=["en:united-kingdom"])
    await client.aclose()
    q = route.calls.last.request.url.params.get("q")
    assert 'categories_tags:"en:colas"' in q
    assert 'countries_tags:"en:united-kingdom"' in q


@respx.mock
async def test_search_category_no_country_clause_by_default(settings):
    """Without countries, the query stays a bare category filter (the unfiltered fallback)."""
    route = respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={"hits": []})
    )
    client = OFFClient(settings)
    await client.search_category("en:colas")
    await client.aclose()
    assert route.calls.last.request.url.params.get("q") == 'categories_tags:"en:colas"'


@respx.mock
async def test_search_category_raises_on_rate_limit(settings):
    respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(429)
    )
    client = OFFClient(settings)
    with pytest.raises(OFFError) as exc:
        await client.search_category("en:chocolate-spreads")
    await client.aclose()
    assert exc.value.kind == "rate_limited"


@respx.mock
async def test_fetch_product_retries_on_rate_limit_then_succeeds(settings):
    """A transient 429 is retried with backoff before giving up — it must not bubble up."""
    route = respx.get("https://world.openfoodfacts.org/api/v2/product/123.json").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(200, json={"product": {"product_name": "Nutella", "brands": "Ferrero"}}),
        ]
    )
    client = OFFClient(settings)
    product = await client.fetch_product("123")
    await client.aclose()
    assert product.name == "Nutella"
    assert route.call_count == 3


@respx.mock
async def test_fetch_product_raises_rate_limited_after_exhausting_retries(settings):
    """Persistent 429 still raises rate_limited, after initial try + off_max_retries retries."""
    route = respx.get("https://world.openfoodfacts.org/api/v2/product/123.json").mock(
        return_value=httpx.Response(429)
    )
    client = OFFClient(settings)
    with pytest.raises(OFFError) as exc:
        await client.fetch_product("123")
    await client.aclose()
    assert exc.value.kind == "rate_limited"
    assert route.call_count == 3  # 1 initial + 2 retries (off_max_retries=2)


@respx.mock
async def test_search_category_retries_on_rate_limit_then_succeeds(settings):
    route = respx.get("https://search.openfoodfacts.org/search").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"hits": [{"code": "111"}]}),
        ]
    )
    client = OFFClient(settings)
    cands = await client.search_category("en:colas")
    await client.aclose()
    assert [c.code for c in cands] == ["111"]
    assert route.call_count == 2


@respx.mock
async def test_fetch_product_parses_categories(settings):
    """categories_tags is exposed on the product, most-specific last, as OFF orders it."""
    respx.get("https://world.openfoodfacts.org/api/v2/product/654.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella",
            "categories_tags": ["en:spreads", "en:sweet-spreads", "en:chocolate-spreads"],
        }})
    )
    client = OFFClient(settings)
    product = await client.fetch_product("654")
    await client.aclose()
    assert product.categories == ["en:spreads", "en:sweet-spreads", "en:chocolate-spreads"]


@respx.mock
async def test_fetch_product_uses_first_brand(settings):
    """Multiple comma-separated brands should show only the first."""
    respx.get("https://world.openfoodfacts.org/api/v2/product/321.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella",
            "brands": "Nutella, Yum yum, Ferrero",
        }})
    )
    client = OFFClient(settings)
    product = await client.fetch_product("321")
    await client.aclose()
    assert product.brand == "Nutella"


def test_normalise_parses_nutriments():
    p = _normalise("123", {
        "product_name": "Test",
        "nutriments": {
            "sugars_100g": 2.4, "salt_100g": "0.18", "saturated-fat_100g": 1.1,
            "fiber_100g": 3.2, "proteins_100g": 8.0, "energy-kcal_100g": 250,
        },
    })
    assert p.nutriments["sugars"] == 2.4
    assert p.nutriments["salt"] == 0.18          # string coerced to float
    assert p.nutriments["saturated_fat"] == 1.1
    assert p.nutriments["fibre"] == 3.2
    assert p.nutriments["protein"] == 8.0
    assert p.nutriments["energy_kcal"] == 250


def test_normalise_omits_missing_and_nonnumeric_nutriments():
    p = _normalise("123", {"product_name": "Test", "nutriments": {
        "sugars_100g": "", "salt_100g": "n/a",
    }})
    assert "sugars" not in p.nutriments
    assert "salt" not in p.nutriments


def test_normalise_energy_falls_back_to_kj():
    p = _normalise("123", {"product_name": "Test", "nutriments": {"energy_100g": 1046}})
    # 1046 kJ / 4.184 = 250.0 kcal
    assert p.nutriments["energy_kcal"] == 250.0


def test_normalise_detects_beverage_from_categories():
    p = _normalise("123", {"product_name": "Cola", "categories_tags": ["en:sodas", "en:beverages"]})
    assert p.is_beverage is True


def test_normalise_non_beverage_default():
    p = _normalise("123", {"product_name": "Bar", "categories_tags": ["en:snacks"]})
    assert p.is_beverage is False


@respx.mock
async def test_fetch_product_uses_production_host_by_default(settings):
    route = respx.get("https://world.openfoodfacts.org/api/v2/product/123.json").mock(
        return_value=httpx.Response(200, json={"product": {"product_name": "X"}})
    )
    client = OFFClient(settings)
    product = await client.fetch_product("123")
    await client.aclose()
    assert route.called
    assert product.raw_off_url == "https://world.openfoodfacts.org/product/123/"


@respx.mock
async def test_fetch_product_uses_staging_host_with_basic_auth():
    s = Settings(off_user_agent="TestApp/1.0", off_environment="staging",
                 off_max_retries=0, off_retry_backoff=0.0, _env_file=None)
    route = respx.get("https://world.openfoodfacts.net/api/v2/product/123.json").mock(
        return_value=httpx.Response(200, json={"product": {"product_name": "X"}})
    )
    client = OFFClient(s)
    product = await client.fetch_product("123")
    await client.aclose()
    assert route.called
    auth = route.calls.last.request.headers["authorization"]
    assert auth == "Basic " + base64.b64encode(b"off:off").decode()
    assert product.raw_off_url == "https://world.openfoodfacts.net/product/123/"
