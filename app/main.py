import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.additive_db import AdditiveDB
from app.alternatives import find_better_alternatives
from app.config import Settings
from app.models import OFFError
from app.off_client import OFFClient
from app.off_writer import OFFWriter
from app.presentation import group_factors
from app.scoring.additive_scorer import AdditiveScorer
from app.scoring.food_engine import FoodScoringEngine, uncapped_overall, weighted_overall, weighted_score

BASE_DIR = Path(__file__).parent.parent


def _clean_barcode(raw: str) -> str | None:
    """Trim surrounding whitespace (pasted barcodes carry trailing spaces and
    newlines), then accept only real retail lengths: EAN-8, UPC-A (12), EAN-13,
    GTIN-14 — matching scan.js's normalizeBarcode."""
    b = (raw or "").strip()
    return b if b.isdigit() and 8 <= len(b) <= 14 else None


async def _refetch_after_write(off_client, barcode, *, base_backoff, max_retries=3, ceiling=4.0):
    """Re-fetch a just-written product, tolerating OFF's propagation delay.

    Up to ``max_retries`` retries after the initial fetch, exponential backoff
    from ``base_backoff`` (0.5s -> 0.5/1.0/2.0s), but never waiting past
    ``ceiling`` seconds total. Returns the product, or None if it isn't queryable
    within the budget (the write still succeeded — caller shows a 'refresh
    shortly' notice). Non-not_found OFF errors propagate."""
    deadline = time.monotonic() + ceiling
    for attempt in range(max_retries + 1):
        try:
            return await off_client.fetch_product(barcode)
        except OFFError as e:
            if e.kind != "not_found":
                raise
        if attempt == max_retries:
            return None
        sleep = base_backoff * (2 ** attempt)
        if time.monotonic() + sleep >= deadline:
            return None
        await asyncio.sleep(sleep)
    return None


def create_app() -> FastAPI:
    settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = AdditiveDB(
            BASE_DIR / "data" / "additives_off_taxonomy.json",
            BASE_DIR / "data" / "additives_curated.yaml",
        )
        client = OFFClient(settings)
        writer = OFFWriter(settings)
        engine = FoodScoringEngine(AdditiveScorer(db))
        app.state.off_client = client
        app.state.off_writer = writer
        app.state.scoring_engine = engine
        app.state.settings = settings
        yield
        await client.aclose()

    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    @app.get("/healthz")
    async def health():
        return JSONResponse({"status": "ok"})

    @app.get("/", response_class=HTMLResponse)
    async def search_page(request: Request):
        return templates.TemplateResponse(request, "search.html")

    @app.get("/scan", response_class=HTMLResponse)
    async def scan_page(request: Request):
        return templates.TemplateResponse(request, "scan.html")

    @app.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request):
        return templates.TemplateResponse(request, "history.html")

    @app.get("/overview", response_class=HTMLResponse)
    async def overview_page(request: Request):
        return templates.TemplateResponse(request, "overview.html")

    @app.get("/add", response_class=HTMLResponse)
    async def add_product_page(request: Request, barcode: str = ""):
        return templates.TemplateResponse(request, "add.html", {"barcode": barcode})

    @app.post("/add", response_class=HTMLResponse)
    async def add_product_submit(
        request: Request,
        barcode: str = Form(""),
        name: str = Form(""),
        brand: str = Form(""),
        category: str = Form(""),
        quantity: str = Form(""),
    ):
        name = name.strip()
        clean = _clean_barcode(barcode)
        # Preserve exactly what the user typed when re-rendering on any error.
        form_ctx = {
            "barcode": barcode.strip(), "name": name, "brand": brand.strip(),
            "category": category.strip(), "quantity": quantity.strip(),
        }
        if clean is None:
            return templates.TemplateResponse(
                request, "add.html",
                {**form_ctx, "error": "Enter a valid barcode — 8 to 14 digits."},
                status_code=400,
            )
        if not name:
            return templates.TemplateResponse(
                request, "add.html",
                {**form_ctx, "error": "Product name is required."},
                status_code=400,
            )

        try:
            await request.app.state.off_writer.add_product(
                barcode=clean, name=name,
                brand=form_ctx["brand"] or None,
                category=form_ctx["category"] or None,
                quantity=form_ctx["quantity"] or None,
            )
        except OFFError as e:
            if e.kind == "no_credentials":
                message = Markup("Submitting products isn't configured on this server yet.")
                status = 503
            else:
                message = Markup("Couldn't save to Open Food Facts — please try again.")
                status = 502
            return templates.TemplateResponse(
                request, "add.html", {**form_ctx, "error": message}, status_code=status,
            )

        settings = request.app.state.settings
        product = await _refetch_after_write(
            request.app.state.off_client, clean, base_backoff=settings.off_retry_backoff,
        )
        if product is None:
            return templates.TemplateResponse(request, "add.html", {
                **form_ctx,
                "notice": "Added to Open Food Facts — it may take a moment to appear. "
                          "Refresh shortly to see its Vera score.",
            })
        return RedirectResponse(url=f"/product/{clean}", status_code=303)

    @app.get("/search", response_class=HTMLResponse)
    async def search_results(request: Request, q: str = ""):
        if not q.strip():
            return templates.TemplateResponse(
                request, "search.html", {"error": "Please enter a search term."}
            )
        try:
            results = await request.app.state.off_client.search(q.strip())
        except OFFError:
            return templates.TemplateResponse(
                request, "error.html",
                {"message": "Couldn't reach Open Food Facts — please try again."},
            )
        return templates.TemplateResponse(
            request, "results.html", {"query": q, "results": results}
        )

    @app.get("/product/{off_id}", response_class=HTMLResponse)
    async def product_score(request: Request, off_id: str):
        try:
            product = await request.app.state.off_client.fetch_product(off_id)
        except OFFError as e:
            if e.kind == "not_found":
                return templates.TemplateResponse(request, "add.html", {
                    "barcode": off_id,
                    "notice": "We don't have this product yet — add the details below "
                              "and we'll score it right away.",
                })
            return templates.TemplateResponse(
                request, "error.html",
                {"message": "Couldn't reach Open Food Facts — please try again."},
            )

        result = request.app.state.scoring_engine.score(product)
        overall_score = weighted_overall(result)

        # A failing alternatives lookup must never break the score page.
        # Compare on the uncapped score so the cap doesn't flatten a whole
        # category to the same number (the displayed cards still show capped scores).
        try:
            alternatives = await find_better_alternatives(
                request.app.state.off_client,
                request.app.state.scoring_engine,
                product,
                uncapped_overall(result),
            )
        except OFFError:
            alternatives = []

        return templates.TemplateResponse(request, "product.html", {
            "product": product,
            "result": result,
            "overall_score": overall_score,
            "alternatives": alternatives,
            "factors": group_factors(result),
        })

    return app


# Re-exported for callers/tests that work with raw dimensions + cap.
_weighted_score = weighted_score


app = create_app()
