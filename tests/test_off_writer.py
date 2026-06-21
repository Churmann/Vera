import base64

import pytest
import requests

from app.config import Settings
from app.models import OFFError
from app.off_writer import OFFWriter


class _RecordingProductResource:
    def __init__(self):
        self.calls = []
    def upload_image(self, code, image_data_base64=None, selected=None):
        self.calls.append({"code": code, "b64": image_data_base64, "selected": selected})
        class _R:
            ok = True
            status_code = 200
        return _R()


class _RecordingAPI:
    def __init__(self):
        self.product = _RecordingProductResource()


def _images():
    return {"front": b"\xff\xd8\xfffront", "ingredients": b"\xff\xd8\xffing", "nutrition": b"\xff\xd8\xffnut"}


def _settings(**kw):
    base = dict(off_user_agent="TestApp/1.0", off_username="cem", off_password="pw", _env_file=None)
    return Settings(**{**base, **kw})


async def test_add_product_photos_uploads_three_selected_fields():
    api = _RecordingAPI()
    writer = OFFWriter(_settings(off_image_lang="en"), api_factory=lambda: api)
    await writer.add_product_photos(barcode="3017620422003", images=_images())
    selected = [c["selected"] for c in api.product.calls]
    assert {"front": {"en": {}}} in selected
    assert {"ingredients": {"en": {}}} in selected
    assert {"nutrition": {"en": {}}} in selected
    front_call = next(c for c in api.product.calls if c["selected"] == {"front": {"en": {}}})
    assert front_call["code"] == "3017620422003"
    assert front_call["b64"] == base64.b64encode(b"\xff\xd8\xfffront").decode("utf-8")


async def test_add_product_photos_without_credentials_raises():
    writer = OFFWriter(_settings(off_username=None, off_password=None), api_factory=lambda: None)
    with pytest.raises(OFFError) as exc:
        await writer.add_product_photos(barcode="12345678", images=_images())
    assert exc.value.kind == "no_credentials"


async def test_add_product_photos_request_error_is_write_failed():
    class _BoomResource:
        def upload_image(self, **kw):
            raise requests.ConnectionError("down")
    class _BoomAPI:
        product = _BoomResource()
    writer = OFFWriter(_settings(), api_factory=lambda: _BoomAPI())
    with pytest.raises(OFFError) as exc:
        await writer.add_product_photos(barcode="12345678", images=_images())
    assert exc.value.kind == "write_failed"


async def test_add_product_photos_non_ok_response_is_write_failed():
    class _NotOkResource:
        def upload_image(self, **kw):
            class _R:
                ok = False
                status_code = 400
            return _R()
    class _NotOkAPI:
        product = _NotOkResource()
    writer = OFFWriter(_settings(), api_factory=lambda: _NotOkAPI())
    with pytest.raises(OFFError) as exc:
        await writer.add_product_photos(barcode="12345678", images=_images())
    assert exc.value.kind == "write_failed"
