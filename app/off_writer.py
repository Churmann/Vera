import asyncio

import requests

from app.config import Settings
from app.models import OFFError


class OFFWriter:
    """Writes products to Open Food Facts via the official SDK.

    The SDK is synchronous (requests-based), so the blocking call runs in a
    threadpool to avoid blocking the event loop. Auth is username/password (the
    OFF *username*, not the email); the mandatory User-Agent and the staging vs
    production target both come from Settings. `api_factory` is injectable so
    tests need neither network nor real credentials.
    """

    def __init__(self, settings: Settings, api_factory=None):
        self._settings = settings
        self._api_factory = api_factory or self._build_api

    def _build_api(self):
        from openfoodfacts import API, Environment

        return API(
            user_agent=self._settings.off_user_agent,
            username=self._settings.off_username,
            password=self._settings.off_password,
            environment=Environment.net if self._settings.is_staging else Environment.org,
        )

    async def add_product(self, *, barcode, name, brand=None, category=None, quantity=None):
        if not self._settings.off_username or not self._settings.off_password:
            raise OFFError("Open Food Facts credentials are not configured", "no_credentials")
        body = {"code": barcode, "product_name": name}
        if brand:
            body["brands"] = brand
        if category:
            body["categories"] = category
        if quantity:
            body["quantity"] = quantity
        try:
            await asyncio.to_thread(self._write, body)
        except requests.RequestException as e:
            raise OFFError(f"Failed to write product to Open Food Facts: {e}", "write_failed")

    def _write(self, body):
        return self._api_factory().product.update(body)
