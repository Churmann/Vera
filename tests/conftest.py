import pytest

from app.models import NormalisedProduct


@pytest.fixture
def make_product():
    def _make(**kwargs) -> NormalisedProduct:
        defaults = dict(
            off_id="test123", name="Test Product", brand="Test Brand",
            nutriscore_grade=None, nova_group=None, additives=[],
            ingredients_text=None, image_url=None,
            raw_off_url="https://world.openfoodfacts.org/product/test123/",
            nutriments={}, is_beverage=False,
        )
        return NormalisedProduct(**{**defaults, **kwargs})
    return _make
