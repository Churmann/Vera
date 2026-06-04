from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.additive_db import AdditiveDB
from app.config import Settings
from app.models import DimensionScore, OFFError
from app.off_client import OFFClient
from app.scoring.additive_scorer import AdditiveScorer
from app.scoring.food_engine import FoodScoringEngine

BASE_DIR = Path(__file__).parent.parent


def create_app() -> FastAPI:
    settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = AdditiveDB(
            BASE_DIR / "data" / "additives_off_taxonomy.json",
            BASE_DIR / "data" / "additives_curated.yaml",
        )
        client = OFFClient(settings)
        engine = FoodScoringEngine(AdditiveScorer(db))
        app.state.off_client = client
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
                return templates.TemplateResponse(
                    request, "error.html",
                    {"message": "Product not found on Open Food Facts."},
                    status_code=404,
                )
            return templates.TemplateResponse(
                request, "error.html",
                {"message": "Couldn't reach Open Food Facts — please try again."},
            )

        result = request.app.state.scoring_engine.score(product)

        return templates.TemplateResponse(request, "product.html", {
            "product": product,
            "result": result,
            "overall_score": _weighted_score(result.dimensions, result.score_cap),
        })

    return app


def _weighted_score(dims: list[DimensionScore], score_cap: int | None) -> int:
    total = round(sum(d.score * d.weight_default for d in dims))
    return min(total, score_cap) if score_cap is not None else total


app = create_app()
