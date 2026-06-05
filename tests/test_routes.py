import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app


def test_health_route():
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_search_page_returns_200():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200


def test_empty_search_shows_error():
    with TestClient(app) as client:
        response = client.get("/search?q=")
    assert response.status_code == 200
    assert "Please enter a search term" in response.text


@respx.mock
def test_search_returns_results():
    respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={
            "hits": [{"code": "123", "product_name": "Nutella", "brands": ["Ferrero"], "image_url": None}]
        })
    )
    with TestClient(app) as client:
        response = client.get("/search?q=nutella")
    assert response.status_code == 200
    assert "Nutella" in response.text


@respx.mock
def test_search_off_error_shows_error_page():
    respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(429)
    )
    with TestClient(app) as client:
        response = client.get("/search?q=nutella")
    assert response.status_code == 200
    assert "open food facts" in response.text.lower()


@respx.mock
def test_product_page_returns_200():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella", "brands": "Ferrero",
            "nutriscore_grade": "e", "nova_group": 4,
            "additives_tags": ["en:e322-lecithins"],
            "ingredients_text": "Sugar, palm oil", "image_url": None,
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    assert response.status_code == 200
    assert "Nutella" in response.text


@respx.mock
def test_product_page_shows_fixed_weights_not_sliders():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella", "brands": "Ferrero",
            "nutriscore_grade": "c", "nova_group": 4,
            "additives_tags": ["en:e322-lecithins"],
            "ingredients_text": "Sugar, palm oil", "image_url": None,
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    text = response.text
    # Fixed weights are shown transparently...
    assert "50%" in text and "30%" in text and "20%" in text
    assert "Why these weights" in text
    # ...but cannot be changed by the user.
    assert 'type="range"' not in text
    assert "weight-slider" not in text
    assert "Reset to defaults" not in text


@respx.mock
def test_product_page_overall_score_is_server_rendered():
    """The overall number must be present in the server HTML, not computed client-side."""
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella", "brands": "Ferrero",
            "nutriscore_grade": "b", "nova_group": 1,
            "additives_tags": [],
            "ingredients_text": "Hazelnuts", "image_url": None,
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    # No client-side scoring payload should be emitted any more.
    assert "score-data" not in response.text
    assert "scorer.js" not in response.text


@respx.mock
def test_product_page_shows_category_icon_and_risk_text():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella", "brands": "Ferrero",
            "nutriscore_grade": "c", "nova_group": 4,
            "additives_tags": ["en:e322-lecithins"],
            "ingredients_text": "Sugar, palm oil", "image_url": None,
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    text = response.text
    # An inline SVG icon is rendered for the additive...
    assert "<svg" in text
    assert "additive-icon" in text
    assert 'data-category="emulsifier"' in text  # E322 lecithin
    # ...and the textual risk label is kept (do not rely on colour alone).
    assert "risk-chip" in text


@respx.mock
def test_product_page_shows_better_alternatives():
    # Current product: Nutella, E + NOVA 4 → capped low score.
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella", "brands": "Ferrero",
            "nutriscore_grade": "e", "nova_group": 4, "additives_tags": [],
            "ingredients_text": "Sugar", "image_url": None,
            "categories_tags": ["en:spreads", "en:chocolate-spreads"],
        }})
    )
    respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={"hits": [{"code": "alt1"}, {"code": "alt2"}]})
    )
    respx.get("https://world.openfoodfacts.org/api/v2/product/alt1.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Healthy Spread", "brands": "GoodCo",
            "nutriscore_grade": "a", "nova_group": 1, "additives_tags": [],
            "image_url": "http://img/alt1.jpg", "categories_tags": ["en:chocolate-spreads"],
        }})
    )
    respx.get("https://world.openfoodfacts.org/api/v2/product/alt2.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Better Spread", "brands": "OkCo",
            "nutriscore_grade": "b", "nova_group": 2, "additives_tags": [],
            "image_url": None, "categories_tags": ["en:chocolate-spreads"],
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    text = response.text
    assert "Better alternatives" in text
    assert "Healthy Spread" in text and "Better Spread" in text
    assert "/product/alt1" in text
    # Higher-scoring alternative shown first.
    assert text.index("Healthy Spread") < text.index("Better Spread")


@respx.mock
def test_product_page_shows_no_alternatives_note():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella", "brands": "Ferrero",
            "nutriscore_grade": "a", "nova_group": 1, "additives_tags": [],
            "ingredients_text": "Hazelnuts", "image_url": None,
            "categories_tags": ["en:spreads", "en:chocolate-spreads"],
        }})
    )
    respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={"hits": [{"code": "alt1"}]})
    )
    respx.get("https://world.openfoodfacts.org/api/v2/product/alt1.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Worse Spread", "brands": "MehCo",
            "nutriscore_grade": "d", "nova_group": 4, "additives_tags": [],
            "image_url": None, "categories_tags": ["en:chocolate-spreads"],
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    assert "No better alternatives found" in response.text


@respx.mock
def test_product_page_renders_when_alternatives_lookup_fails():
    """A failing alternatives lookup must not break the main score page."""
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Nutella", "brands": "Ferrero",
            "nutriscore_grade": "c", "nova_group": 2, "additives_tags": [],
            "ingredients_text": "Sugar", "image_url": None,
            "categories_tags": ["en:chocolate-spreads"],
        }})
    )
    respx.get("https://search.openfoodfacts.org/search").mock(return_value=httpx.Response(429))
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    assert response.status_code == 200
    assert "Nutella" in response.text
    assert "No better alternatives found" in response.text


@respx.mock
def test_product_not_found_returns_404():
    respx.get("https://world.openfoodfacts.org/api/v2/product/000.json").mock(
        return_value=httpx.Response(404, json={"status": 0})
    )
    with TestClient(app) as client:
        response = client.get("/product/000")
    assert response.status_code == 404
