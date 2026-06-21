import asyncio
import base64

import requests

from app.config import Settings
from app.models import OFFError


def use_os_trust_store() -> None:
    """Verify the SDK's TLS against the OS trust store, mirroring the read path.

    OFFClient already routes reads through ``truststore`` (see
    ``app/off_client.py`` ``_ssl_verify``) so they survive a TLS-intercepting
    proxy/antivirus. The openfoodfacts SDK builds its own requests/urllib3
    session with no hook to inject an SSL context, so we patch the stdlib once at
    startup instead. On a normal host (including Render) the OS store holds the
    standard CA roots, so this verifies exactly like certifi — a no-op in
    practice; behind TLS interception it lets the locally-trusted root validate
    so writes succeed like reads. If ``truststore`` is unavailable it's skipped,
    falling back to the SDK's certifi bundle — same defensive fallback as reads.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass


class OFFWriter:
    """Writes products to Open Food Facts via the official SDK.

    The SDK is synchronous (requests-based), so the blocking call runs in a
    threadpool to avoid blocking the event loop. Auth is username/password (the
    OFF *username*, not the email); the mandatory User-Agent and the staging vs
    production target both come from Settings. `api_factory` is injectable so
    tests need neither network nor real credentials.
    """

    _IMAGE_FIELDS = ("front", "ingredients", "nutrition")

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

    async def add_product_photos(self, *, barcode, images):
        """Upload front/ingredients/nutrition photos for ``barcode``.

        ``images`` maps field name -> raw bytes. Each is base64-encoded and
        uploaded via ``product.upload_image(..., selected={field: {lang: {}}})``
        in a threadpool (the SDK is synchronous). Uploading an image to a barcode
        creates the product in OFF, so no separate text write is needed."""
        if not self._settings.off_username or not self._settings.off_password:
            raise OFFError("Open Food Facts credentials are not configured", "no_credentials")
        try:
            await asyncio.to_thread(self._upload_all, barcode, images)
        except requests.RequestException as e:
            raise OFFError(f"Failed to upload product photos to Open Food Facts: {e}", "write_failed")

    def _upload_all(self, barcode, images):
        api = self._api_factory()
        lang = self._settings.off_image_lang
        for field in self._IMAGE_FIELDS:
            b64 = base64.b64encode(images[field]).decode("utf-8")
            resp = api.product.upload_image(
                code=barcode,
                image_data_base64=b64,
                selected={field: {lang: {}}},
            )
            if not getattr(resp, "ok", True):
                raise OFFError(
                    f"Open Food Facts rejected the image upload "
                    f"({getattr(resp, 'status_code', '?')})",
                    "write_failed",
                )
