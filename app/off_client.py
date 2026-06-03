import time
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.models import NormalisedProduct, OFFError

_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
_FIELDS = "code,product_name,brands,image_url,nutriscore_grade,nova_group,additives_tags,ingredients_text"


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
        )
        self._cache: dict[str, tuple[NormalisedProduct, float]] = {}
        self._ttl = settings.off_cache_ttl

    async def search(self, query: str) -> list[ProductSummary]:
        try:
            resp = await self._client.get(_SEARCH_URL, params={
                "search_terms": query, "search_simple": 1,
                "action": "process", "json": 1,
                "page_size": 10, "fields": _FIELDS,
            })
        except httpx.TimeoutException:
            raise OFFError("Request timed out", "timeout")
        except httpx.NetworkError as e:
            raise OFFError(str(e), "network_error")

        if resp.status_code == 429:
            raise OFFError("Rate limit reached", "rate_limited")
        resp.raise_for_status()

        results = []
        for p in resp.json().get("products", []):
            code = p.get("code", "").strip()
            name = p.get("product_name", "").strip()
            if not code or not name:
                continue
            results.append(ProductSummary(
                off_id=code,
                name=name,
                brand=p.get("brands", "").strip() or None,
                image_url=p.get("image_url") or None,
            ))
        return results

    async def fetch_product(self, off_id: str) -> NormalisedProduct:
        cached = self._cache.get(off_id)
        if cached and time.monotonic() - cached[1] < self._ttl:
            return cached[0]

        try:
            resp = await self._client.get(
                _PRODUCT_URL.format(code=off_id),
                params={"fields": _FIELDS},
            )
        except httpx.TimeoutException:
            raise OFFError("Request timed out", "timeout")
        except httpx.NetworkError as e:
            raise OFFError(str(e), "network_error")

        if resp.status_code == 404:
            raise OFFError(f"Product {off_id} not found", "not_found")
        if resp.status_code == 429:
            raise OFFError("Rate limit reached", "rate_limited")
        resp.raise_for_status()

        data = resp.json()
        if not data.get("product"):
            raise OFFError(f"Product {off_id} not found", "not_found")

        product = _normalise(off_id, data["product"])
        self._cache[off_id] = (product, time.monotonic())
        return product

    async def aclose(self) -> None:
        await self._client.aclose()


def _normalise(off_id: str, p: dict) -> NormalisedProduct:
    additives: list[str] = []
    for tag in p.get("additives_tags", []):
        parts = tag.split(":")
        code_part = parts[-1].split("-")[0] if parts else ""
        if code_part.startswith("e") and len(code_part) >= 2:
            additives.append(code_part)

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
        brand=(p.get("brands") or "").strip() or None,
        nutriscore_grade=grade,
        nova_group=nova,
        additives=additives,
        ingredients_text=(p.get("ingredients_text") or "").strip() or None,
        image_url=p.get("image_url") or None,
        raw_off_url=f"https://world.openfoodfacts.org/product/{off_id}/",
    )
