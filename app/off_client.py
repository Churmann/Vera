import ssl
import time
from dataclasses import dataclass

import httpx
import truststore

from app.config import Settings
from app.models import NormalisedProduct, OFFError

# /cgi/search.pl is permanently deprecated (503); full-text search moved to search-a-licious.
_SEARCH_URL = "https://search.openfoodfacts.org/search"
_SEARCH_FIELDS = "code,product_name,brands,image_url"
_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
_PRODUCT_FIELDS = "code,product_name,brands,image_url,nutriscore_grade,nova_group,additives_tags,ingredients_text,categories_tags"


@dataclass
class ProductSummary:
    off_id: str
    name: str
    brand: str | None
    image_url: str | None


class OFFClient:
    def __init__(self, settings: Settings):
        self._client = httpx.AsyncClient(
            headers={"User-Agent": settings.off_user_agent},
            timeout=settings.off_request_timeout,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )
        self._cache: dict[str, tuple[NormalisedProduct, float]] = {}
        self._ttl = settings.off_cache_ttl

    async def search(self, query: str) -> list[ProductSummary]:
        try:
            resp = await self._client.get(_SEARCH_URL, params={
                "q": query,
                "page_size": 10,
                "fields": _SEARCH_FIELDS,
            })
        except httpx.TimeoutException:
            raise OFFError("Request timed out", "timeout")
        except (httpx.NetworkError, httpx.ConnectError, OSError) as e:
            raise OFFError(str(e), "network_error")

        if resp.status_code == 429:
            raise OFFError("Rate limit reached", "rate_limited")
        if resp.status_code >= 500:
            raise OFFError(f"Open Food Facts returned {resp.status_code}", "network_error")
        resp.raise_for_status()

        results = []
        for p in resp.json().get("hits", []):
            code = (p.get("code") or "").strip()
            name = (p.get("product_name") or "").strip()
            if not code or not name:
                continue
            # brands is a list in search-a-licious
            brands_raw = p.get("brands") or []
            brand = brands_raw[0].strip() if brands_raw else None
            results.append(ProductSummary(
                off_id=code,
                name=name,
                brand=brand or None,
                image_url=p.get("image_url") or None,
            ))
        return results

    async def search_category(self, tag: str, page_size: int = 12) -> list[str]:
        """Return product codes in a given OFF category tag (most relevant first)."""
        try:
            resp = await self._client.get(_SEARCH_URL, params={
                "q": f'categories_tags:"{tag}"',
                "page_size": page_size,
                "fields": "code",
            })
        except httpx.TimeoutException:
            raise OFFError("Request timed out", "timeout")
        except (httpx.NetworkError, httpx.ConnectError, OSError) as e:
            raise OFFError(str(e), "network_error")

        if resp.status_code == 429:
            raise OFFError("Rate limit reached", "rate_limited")
        if resp.status_code >= 500:
            raise OFFError(f"Open Food Facts returned {resp.status_code}", "network_error")
        resp.raise_for_status()

        codes = []
        for p in resp.json().get("hits", []):
            code = (p.get("code") or "").strip()
            if code:
                codes.append(code)
        return codes

    async def fetch_product(self, off_id: str) -> NormalisedProduct:
        cached = self._cache.get(off_id)
        if cached and time.monotonic() - cached[1] < self._ttl:
            return cached[0]

        try:
            resp = await self._client.get(
                _PRODUCT_URL.format(code=off_id),
                params={"fields": _PRODUCT_FIELDS},
            )
        except httpx.TimeoutException:
            raise OFFError("Request timed out", "timeout")
        except (httpx.NetworkError, httpx.ConnectError, OSError) as e:
            raise OFFError(str(e), "network_error")

        if resp.status_code == 404:
            raise OFFError(f"Product {off_id} not found", "not_found")
        if resp.status_code == 429:
            raise OFFError("Rate limit reached", "rate_limited")
        if resp.status_code >= 500:
            raise OFFError(f"Open Food Facts returned {resp.status_code}", "network_error")
        resp.raise_for_status()

        data = resp.json()
        if not data.get("product"):
            raise OFFError(f"Product {off_id} not found", "not_found")

        product = _normalise(off_id, data["product"])
        self._cache[off_id] = (product, time.monotonic())
        return product

    async def aclose(self) -> None:
        await self._client.aclose()


import re as _re
# OFF uses Roman-numeral suffixes for subtypes (e322i, e322ii, e500iii).
# Single-letter suffixes (e160a, e160b, e160c) mark genuinely distinct additives — don't strip those.
_ROMAN_SUBTYPE = _re.compile(r"^(e\d+)([ivx]+)$")


def _collapse_e_number(code: str) -> str:
    m = _ROMAN_SUBTYPE.match(code)
    return m.group(1) if m else code


def _normalise(off_id: str, p: dict) -> NormalisedProduct:
    seen: set[str] = set()
    additives: list[str] = []
    for tag in p.get("additives_tags", []):
        parts = tag.split(":")
        code_part = parts[-1].split("-")[0] if parts else ""
        if code_part.startswith("e") and len(code_part) >= 2:
            base = _collapse_e_number(code_part)
            if base not in seen:
                seen.add(base)
                additives.append(base)

    grade = (p.get("nutriscore_grade") or "").upper().strip()
    grade = grade if grade in ("A", "B", "C", "D", "E") else None

    nova: int | None = None
    try:
        nova_raw = p.get("nova_group")
        if nova_raw is not None:
            nova = int(nova_raw)
            if nova not in (1, 2, 3, 4):
                nova = None
    except (ValueError, TypeError):
        pass

    return NormalisedProduct(
        off_id=off_id,
        name=(p.get("product_name") or "").strip() or "Unknown product",
        brand=(p.get("brands") or "").split(",")[0].strip() or None,
        nutriscore_grade=grade,
        nova_group=nova,
        additives=additives,
        ingredients_text=(p.get("ingredients_text") or "").strip() or None,
        image_url=p.get("image_url") or None,
        raw_off_url=f"https://world.openfoodfacts.org/product/{off_id}/",
        categories=[c for c in (p.get("categories_tags") or []) if c],
    )
