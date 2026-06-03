import httpx
import pytest
import respx

from app.config import Settings
from app.models import OFFError
from app.off_client import OFFClient


@pytest.fixture
def settings():
    return Settings(off_user_agent="TestApp/1.0", off_request_timeout=5.0, off_cache_ttl=300)


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
