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


def test_search_page_links_to_scan():
    # The search hero offers a Scan barcode shortcut.
    with TestClient(app) as client:
        response = client.get("/")
    assert 'href="/scan"' in response.text
    assert "Scan barcode" in response.text


def test_nav_includes_scan_link_on_every_page():
    # The Scan entry point lives in the shared header nav.
    with TestClient(app) as client:
        response = client.get("/")
    assert '<a href="/scan"' in response.text


def test_scan_page_returns_200_with_camera_wiring():
    with TestClient(app) as client:
        response = client.get("/scan")
    assert response.status_code == 200
    body = response.text
    # The camera viewport, the ZXing library (SRI-pinned), and the scan module.
    assert 'id="scan-video"' in body
    assert "zxing-browser.min.js" in body
    assert "integrity=" in body
    assert "/static/js/scan.js" in body


def test_scan_page_offers_manual_fallback():
    # Every failure mode (no camera, denied, etc.) can fall back to typing.
    with TestClient(app) as client:
        response = client.get("/scan")
    assert 'id="scan-manual-form"' in response.text
    assert 'id="scan-manual-input"' in response.text


def test_scan_nav_link_is_active_on_scan_page():
    with TestClient(app) as client:
        response = client.get("/scan")
    assert 'href="/scan" class="site-nav-link is-active"' in response.text


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
def test_product_page_groups_factors_into_negatives_and_positives():
    # Nutella: Nutri-Score E (poor) + NOVA 4 (poor) + one low-risk additive (E322).
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
    # Scope to the breakdown section (dimension labels also appear in the
    # weights panel above it).
    factors = response.text[response.text.index('id="factors"'):]
    # Both group headings are present as text labels (not colour alone).
    assert "Negatives" in factors
    assert "Positives" in factors
    # Poor dimensions land in Negatives, ahead of the Positives heading.
    neg = factors.index("Negatives")
    pos = factors.index("Positives")
    assert neg < factors.index("Nutritional Quality") < pos
    assert neg < factors.index("Processing Level") < pos
    # The low-risk additive (E322 lecithin) sits in the Positives group.
    assert pos < factors.index("Lecithin")
    # Each row exposes its detail behind an expandable control.
    assert 'class="factor"' in factors
    assert "factor-dot" in factors


@respx.mock
def test_product_page_explains_dimensions_in_plain_language():
    # Nutella: Nutri-Score E + NOVA 4 + one low-risk additive (E322 lecithin).
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
    factors = response.text[response.text.index('id="factors"'):]
    # Each dimension leads with the plain band, kept beside its score number...
    assert "factor-plain-band" in factors
    assert "Ultra-processed" in factors
    # ...with the jargon demoted to a smaller supporting sub-label...
    assert "factor-tech" in factors
    assert "NOVA group 4" in factors
    # ...and a consistent info icon carrying the plain explanation.
    assert "factor-info" in factors
    assert "What this means" in factors
    # The plain-language explanations themselves (education over jargon):
    assert "cook with at home" in factors                       # processing
    assert "A (best) to E (worst)" in factors                   # nutrition
    assert "most approved additives are low-risk" in factors    # additives


@respx.mock
def test_additives_explanation_shown_once_not_repeated_per_row():
    # A Coke-Zero-style product with several additives. The generic "what
    # additives means" explanation must appear once on the section, never once
    # per additive row (which would read as clutter).
    additives = ["en:e150d", "en:e338", "en:e950", "en:e951", "en:e955"]
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Coca-Cola Zero", "brands": "Coca-Cola",
            "nutriscore_grade": "e", "nova_group": 4,
            "additives_tags": additives,
            "ingredients_text": "Water", "image_url": None,
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    factors = response.text[response.text.index('id="factors"'):]
    # Exactly one additives explanation, despite five additive rows.
    assert factors.count("most approved additives are low-risk") == 1
    # The dimension info icons stay (one each for nutrition + processing).
    assert factors.count('class="factor-info"') == 2


@respx.mock
def test_additives_explanation_is_a_subtle_disclosure_under_the_additives():
    additives = ["en:e150d", "en:e338", "en:e950", "en:e951", "en:e955"]
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Coca-Cola Zero", "brands": "Coca-Cola",
            "nutriscore_grade": "e", "nova_group": 4,
            "additives_tags": additives,
            "ingredients_text": "Water", "image_url": None,
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    factors = response.text[response.text.index('id="factors"'):]
    # The explanation is a subtle, optional "What are additives?" affordance...
    assert "What are additives?" in factors
    assert "additives-info" in factors
    assert "factor-additives-note" not in factors  # the old floating note is gone
    # ...tied to the flagged additives in the Negatives group (directly under the
    # additive rows), not floating at the very bottom after Positives.
    assert factors.index("What are additives?") > factors.index("Aspartame")
    assert factors.index("What are additives?") < factors.index("Positives")
    # ...revealing the same plain-language explanation when opened.
    assert "most approved additives are low-risk" in factors


@respx.mock
def test_product_page_caps_many_low_risk_additives_but_shows_all_negatives():
    additives = [f"en:e{n}" for n in range(500, 512)]  # 12 unknown -> low-tail additives
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Additive Soup", "brands": "TestCo",
            "nutriscore_grade": "e", "nova_group": 4,
            "additives_tags": additives,
            "ingredients_text": "Everything", "image_url": None,
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    text = response.text
    # The reassuring long tail is tucked behind a single disclosure...
    assert "more low-risk additive" in text
    # ...while the poor core dimensions (Negatives) are always shown in full.
    assert "Nutritional Quality" in text
    assert "Processing Level" in text


@respx.mock
def test_unnamed_additive_does_not_double_the_e_number():
    """An unclassified additive (no name) should show its E-number once, not 'E999 (E999)'."""
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Mystery Drink", "brands": "TestCo",
            "nutriscore_grade": "e", "nova_group": 4,
            "additives_tags": ["en:e999"],  # not in our DB -> name falls back to E999
            "ingredients_text": "Water", "image_url": None,
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    text = response.text
    # The label already is "E999"; the parenthesised enum span must be suppressed
    # so the visible row reads "E999", not "E999 (E999)".
    assert "(E999)" not in text
    assert "E999" in text


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
        return_value=httpx.Response(200, json={"hits": [
            {"code": "alt1", "nutriscore_grade": "a", "nova_group": 1},
            {"code": "alt2", "nutriscore_grade": "b", "nova_group": 2},
        ]})
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
    # Each card carries an honest reason it's a better pick.
    assert "alt-reason" in text
    assert "vs E" in text  # current product is Nutri-Score E


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
def test_product_not_found_shows_add_form_prefilled():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422000.json").mock(
        return_value=httpx.Response(404, json={"status": 0})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422000")
    assert response.status_code == 200
    body = response.text
    assert 'action="/add"' in body
    assert 'value="3017620422000"' in body  # barcode prefilled


def test_nav_present_across_pages():
    with TestClient(app) as client:
        for path in ("/", "/history", "/overview"):
            text = client.get(path).text
            assert 'href="/history"' in text
            assert 'href="/overview"' in text
            assert "site-nav" in text


def test_history_page_scaffolding():
    with TestClient(app) as client:
        response = client.get("/history")
    text = response.text
    assert response.status_code == 200
    assert "<h1>History</h1>" in text
    # Empty-state and management controls are server-rendered (JS toggles them).
    assert 'id="history-empty"' in text
    assert 'id="history-clear"' in text
    assert 'id="history-list"' in text
    assert "/static/js/history.js" in text


def test_overview_page_scaffolding():
    with TestClient(app) as client:
        response = client.get("/overview")
    text = response.text
    assert response.status_code == 200
    assert "<h1>Overview</h1>" in text
    assert 'id="overview-empty"' in text
    assert 'id="overview-chart"' in text
    assert "/static/js/history.js" in text


@respx.mock
def test_product_page_emits_history_record_without_forbidden_strings():
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
    text = response.text
    # The hidden recorder carries the data history.js needs...
    assert 'id="history-record"' in text
    assert 'data-product-id="3017620422003"' in text
    assert 'data-band=' in text
    # ...while still not reintroducing the forbidden client-scoring strings.
    assert "score-data" not in text
    assert "scorer.js" not in text


@respx.mock
def test_product_page_renders_nutrient_bars():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Granola", "nutriscore_grade": "c", "nova_group": 3,
            "additives_tags": [], "ingredients_text": "Oats", "image_url": None,
            "nutriments": {"sugars_100g": 21.3, "salt_100g": 0.2,
                           "saturated-fat_100g": 2.1, "fiber_100g": 7.4,
                           "proteins_100g": 9.2, "energy-kcal_100g": 432},
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    assert response.status_code == 200
    body = response.text
    assert "nutrient-bar" in body          # the bar component rendered
    assert "Saturated fat" in body
    assert "per 100 g" in body


def test_add_page_renders_form():
    with TestClient(app) as client:
        response = client.get("/add")
    assert response.status_code == 200
    body = response.text
    assert 'action="/add"' in body and 'method="post"' in body
    assert 'name="barcode"' in body
    assert 'name="name"' in body
    assert 'name="brand"' in body
    assert 'name="category"' in body
    assert 'name="quantity"' in body


def test_add_page_prefills_barcode_from_query():
    with TestClient(app) as client:
        response = client.get("/add?barcode=3017620422003")
    assert 'value="3017620422003"' in response.text


@respx.mock
def test_empty_search_results_offer_add_product():
    respx.get("https://search.openfoodfacts.org/search").mock(
        return_value=httpx.Response(200, json={"hits": []})
    )
    with TestClient(app) as client:
        response = client.get("/search?q=nonexistentproduct")
    assert 'href="/add"' in response.text
