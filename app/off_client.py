import asyncio
import ssl
import time
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.models import NormalisedProduct, OFFError


def _ssl_verify():
    """SSL verification setting for the OFF HTTP client.

    Prefer the OS trust store via ``truststore`` so the app keeps working behind
    a TLS-intercepting proxy or antivirus (common on dev machines, e.g. AVG on
    Windows). If truststore is unavailable or fails to initialise — e.g. on a
    minimal Linux host in production — fall back to httpx's default certifi CA
    bundle so the Open Food Facts connection still works everywhere.
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return True  # httpx default verification (certifi CA bundle)

# /cgi/search.pl is permanently deprecated (503); full-text search moved to search-a-licious.
_SEARCH_URL = "https://search.openfoodfacts.org/search"
_SEARCH_FIELDS = "code,product_name,brands,image_url"
_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
_PRODUCT_FIELDS = "code,product_name,brands,image_url,nutriscore_grade,nova_group,additives_tags,ingredients_text,categories_tags"
# Enough to pre-rank a candidate without fetching the full product. additives_tags is
# NOT available from search (only additives_n), so promising candidates are still
# fetched in full for accurate additive scoring.
_CATEGORY_FIELDS = "code,nutriscore_grade,nova_group"


@dataclass
class ProductSummary:
    off_id: str
    name: str
    brand: str | None
    image_url: str | None


@dataclass
class CategoryCandidate:
    """A category-search hit, with just the fields needed to pre-rank it cheaply."""
    code: str
    nutriscore_grade: str | None  # A–E
    nova_group: int | None        # 1–4


class OFFClient:
    def __init__(self, settings: Settings):
        self._client = httpx.AsyncClient(
            headers={"User-Agent": settings.off_user_agent},
            timeout=settings.off_request_timeout,
            verify=_ssl_verify(),
        )
        self._cache: dict[str, tuple[NormalisedProduct, float]] = {}
        self._ttl = settings.off_cache_ttl
        self._max_retries = settings.off_max_retries
        self._retry_backoff = settings.off_retry_backoff

    async def _get(self, url: str, params: dict) -> httpx.Response:
        """GET with exponential backoff retry on HTTP 429. Transport failures map to
        OFFError immediately (not retried). Status-code interpretation is left to the
        caller; a persistently rate-limited request returns the final 429 response."""
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.get(url, params=params)
            except httpx.TimeoutException:
                raise OFFError("Request timed out", "timeout")
            except (httpx.NetworkError, httpx.ConnectError, OSError) as e:
                raise OFFError(str(e), "network_error")
            if resp.status_code == 429 and attempt < self._max_retries:
                await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                continue
            return resp
        return resp  # all attempts were 429 — caller raises rate_limited

    async def search(self, query: str) -> list[ProductSummary]:
        resp = await self._get(_SEARCH_URL, params={
            "q": query,
            "page_size": 10,
            "fields": _SEARCH_FIELDS,
        })

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

    async def search_category(self, tag: str, page_size: int = 12) -> list[CategoryCandidate]:
        """Return candidates in a given OFF category tag, each carrying the Nutri-Score
        and NOVA needed to pre-rank it before deciding whether to fetch it in full."""
        resp = await self._get(_SEARCH_URL, params={
            "q": f'categories_tags:"{tag}"',
            "page_size": page_size,
            "fields": _CATEGORY_FIELDS,
            # A bare category filter has no relevance ranking, so OFF otherwise
            # returns a varying page. Sort by popularity for a stable, recognisable set.
            "sort_by": "-popularity_key",
        })

        if resp.status_code == 429:
            raise OFFError("Rate limit reached", "rate_limited")
        if resp.status_code >= 500:
            raise OFFError(f"Open Food Facts returned {resp.status_code}", "network_error")
        resp.raise_for_status()

        candidates = []
        for p in resp.json().get("hits", []):
            code = (p.get("code") or "").strip()
            if code:
                candidates.append(CategoryCandidate(
                    code=code,
                    nutriscore_grade=_parse_grade(p.get("nutriscore_grade")),
                    nova_group=_parse_nova(p.get("nova_group")),
                ))
        return candidates

    async def fetch_product(self, off_id: str) -> NormalisedProduct:
        cached = self._cache.get(off_id)
        if cached and time.monotonic() - cached[1] < self._ttl:
            return cached[0]

        resp = await self._get(
            _PRODUCT_URL.format(code=off_id),
            params={"fields": _PRODUCT_FIELDS},
        )

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


def _parse_grade(raw) -> str | None:
    grade = (raw or "").upper().strip()
    return grade if grade in ("A", "B", "C", "D", "E") else None


def _parse_nova(raw) -> int | None:
    try:
        if raw is not None:
            nova = int(raw)
            if nova in (1, 2, 3, 4):
                return nova
    except (ValueError, TypeError):
        pass
    return None


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

    return NormalisedProduct(
        off_id=off_id,
        name=(p.get("product_name") or "").strip() or "Unknown product",
        brand=(p.get("brands") or "").split(",")[0].strip() or None,
        nutriscore_grade=_parse_grade(p.get("nutriscore_grade")),
        nova_group=_parse_nova(p.get("nova_group")),
        additives=additives,
        ingredients_text=(p.get("ingredients_text") or "").strip() or None,
        image_url=p.get("image_url") or None,
        raw_off_url=f"https://world.openfoodfacts.org/product/{off_id}/",
        categories=[c for c in (p.get("categories_tags") or []) if c],
    )
