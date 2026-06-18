import pytest
import requests

from app.config import Settings
from app.models import OFFError
from app.off_writer import OFFWriter


class _FakeProductResource:
    def __init__(self, sink):
        self._sink = sink

    def update(self, body):
        self._sink.append(body)
        return {"status": 1}


class _FakeAPI:
    def __init__(self, sink):
        self.product = _FakeProductResource(sink)


def _settings(**kw):
    base = dict(off_user_agent="TestApp/1.0", off_username="cem", off_password="pw", _env_file=None)
    return Settings(**{**base, **kw})


async def test_add_product_builds_minimal_body_and_omits_empty_optionals():
    sink = []
    writer = OFFWriter(_settings(off_environment="staging"), api_factory=lambda: _FakeAPI(sink))
    await writer.add_product(barcode="3017620422003", name="Nutella",
                             brand="", category=None, quantity="400 g")
    assert sink == [{"code": "3017620422003", "product_name": "Nutella", "quantity": "400 g"}]


async def test_add_product_includes_all_fields_when_present():
    sink = []
    writer = OFFWriter(_settings(), api_factory=lambda: _FakeAPI(sink))
    await writer.add_product(barcode="12345678", name="X", brand="B",
                             category="Snacks", quantity="100 g")
    assert sink[0] == {"code": "12345678", "product_name": "X",
                       "brands": "B", "categories": "Snacks", "quantity": "100 g"}


async def test_add_product_without_credentials_raises_no_credentials():
    writer = OFFWriter(_settings(off_username=None, off_password=None),
                       api_factory=lambda: None)
    with pytest.raises(OFFError) as exc:
        await writer.add_product(barcode="12345678", name="X")
    assert exc.value.kind == "no_credentials"


async def test_add_product_maps_write_failure_to_offerror():
    class _BoomResource:
        def update(self, body):
            raise requests.ConnectionError("down")

    class _BoomAPI:
        product = _BoomResource()

    writer = OFFWriter(_settings(), api_factory=lambda: _BoomAPI())
    with pytest.raises(OFFError) as exc:
        await writer.add_product(barcode="12345678", name="X")
    assert exc.value.kind == "write_failed"
