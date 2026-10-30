"""EarthPulse AI web service: JSON/NDJSON API plus the static frontend."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .agents import orchestrator
from .agents.taste import SEARCH_TYPES
from .agents.trace import StageFailed
from .config import Settings, get_settings
from .llm import LLM
from .models import CompareRequest, RunRequest
from .qloo.client import QlooClient, QlooError
from .qloo.taxonomy import CATEGORIES, DEFAULT_CATEGORIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("earthpulse")
STATIC = Path(__file__).resolve().parent.parent / "static"


class RateLimiter:
    """Sliding-window limit per client IP (in memory; one Render instance)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)

    def allow(self, ip: str, bucket: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        q = self._hits[(ip, bucket)]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def build_qloo(settings: Settings) -> QlooClient:
    if settings.fixtures_active:
        from .qloo import fixtures

        log.warning("EARTHPULSE_DEV_FIXTURES active: serving SYNTHETIC data, not Qloo.")
        return QlooClient(dataclasses.replace(settings, qloo_api_key="synthetic-fixtures"), transport=fixtures.transport())
    return QlooClient(settings)


def create_app(settings: Settings | None = None, qloo: QlooClient | None = None, llm: LLM | None = None,
               geo_transport=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.qloo.aclose()

    app = FastAPI(title="EarthPulse AI", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.qloo = qloo or build_qloo(settings)
    app.state.llm = llm or LLM(settings)
    app.state.limiter = RateLimiter()
    app.state.geo_transport = geo_transport

    def err(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def _bad(_: Request, exc: RequestValidationError):
        msgs = []
        for e in exc.errors():
            m = str(e.get("msg", "invalid input")).removeprefix("Value error, ")
            loc = ".".join(str(x) for x in e.get("loc", [])[1:])
            msgs.append(f"{loc}: {m}" if loc else m)
        return err(422, "invalid_request", "; ".join(msgs)[:400])

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__, "qloo_configured": settings.qloo_configured,
                "llm_configured": settings.llm_configured, "fixtures": settings.fixtures_active,
                "categories": [{"key": k, "label": c.label, "default": k in DEFAULT_CATEGORIES}
                               for k, c in CATEGORIES.items()]}

    @app.get("/api/search")
    async def search(request: Request, q: str = Query(min_length=2, max_length=120)):
        if not app.state.limiter.allow(client_ip(request), "search", settings.search_per_10min_per_ip, 600):
            return err(429, "rate_limited", "Too many searches. Please wait a few minutes.")
        try:
            hits = await app.state.qloo.search(q, types=SEARCH_TYPES, take=6)
        except QlooError as e:
            status = {"qloo_not_configured": 503, "qloo_rate_limited": 429}.get(e.code, 502)
            return err(status, e.code, e.user_message)
        return {"results": [{"entity_id": h.entity_id, "name": h.name, "kind": h.kind, "image_url": h.image_url,
                             "disambiguation": h.disambiguation} for h in hits]}

    def stream(request: Request, work) -> StreamingResponse | JSONResponse:
        if not app.state.limiter.allow(client_ip(request), "run", settings.runs_per_hour_per_ip, 3600):
            return err(429, "rate_limited", "You've reached this demo's hourly limit. Please try again later.")
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(ev: dict) -> None:
            await queue.put(ev)

        async def runner():
            try:
                result = await work(emit)
                await queue.put(result)
            except StageFailed as e:
                await queue.put({"type": "error", "code": e.code, "message": e.message})
            except QlooError as e:
                await queue.put({"type": "error", "code": e.code, "message": e.user_message})
            except Exception:  # noqa: BLE001
                log.exception("run.crashed")
                await queue.put({"type": "error", "code": "internal", "message": "Something went wrong on our side."})
            finally:
                await queue.put(None)

        async def gen():
            task = asyncio.create_task(runner())
            try:
                yield json.dumps({"type": "start", "fixtures": settings.fixtures_active}) + "\n"
                while True:
                    ev = await queue.get()
                    if ev is None:
                        break
                    yield json.dumps(ev, default=str) + "\n"
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(gen(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/run")
    async def run(request: Request, body: RunRequest):
        return stream(request, lambda emit: orchestrator.run(
            body, client=app.state.qloo, llm=app.state.llm, settings=settings, emit=emit,
            geo_transport=app.state.geo_transport))

    @app.post("/api/compare")
    async def compare(request: Request, body: CompareRequest):
        return stream(request, lambda emit: orchestrator.compare(
            body, client=app.state.qloo, llm=app.state.llm, settings=settings, emit=emit,
            geo_transport=app.state.geo_transport))

    @app.get("/api/check")
    async def check(request: Request, prompt: str = Query(min_length=3, max_length=400),
                    location: str = Query(min_length=2, max_length=120),
                    categories: str = Query(default=",".join(DEFAULT_CATEGORIES), max_length=200),
                    days: int = Query(default=2, ge=1, le=2), compare: bool = False):
        """Read-only, condensed run for verifying a deployment (e.g. scripts/evaluate.py --url).

        Returns stage outcomes, counts, measured metrics and grounding results, plus place names
        only as the app itself would show them. Rate-limited like /api/run.
        """
        if not app.state.limiter.allow(client_ip(request), "run", settings.runs_per_hour_per_ip, 3600):
            return err(429, "rate_limited", "You've reached this demo's hourly limit. Please try again later.")
        try:
            body = CompareRequest(prompt=prompt, location=location, days=days,
                                  categories=[c.strip() for c in categories.split(",") if c.strip()])
        except ValueError as e:
            return err(422, "invalid_request", str(e)[:300])
        kw = dict(client=app.state.qloo, llm=app.state.llm, settings=settings, geo_transport=app.state.geo_transport)
        started = time.monotonic()
        try:
            res = await (orchestrator.compare(body, **kw) if compare else orchestrator.run(body, **kw))
        except StageFailed as e:
            return {"ok": False, "code": e.code, "message": e.message}
        except QlooError as e:
            return {"ok": False, "code": e.code, "message": e.user_message}
        out = {"ok": True, "ms": int((time.monotonic() - started) * 1000), "fixtures": res["fixtures"],
               "stats": res["stats"], "seeds": [{k: s.get(k) for k in ("input", "name", "kind", "resolved_as")}
                                                for s in res["seeds"]],
               "stages": [{k: st[k] for k in ("id", "status", "ms", "detail")} for st in res["trace"]],
               "per_category": next((st.get("data", {}).get("per_category") for st in res["trace"]
                                     if st["id"] == "discovery"), None)}
        if compare:
            out.update(overlap=res["overlap"], overlap_footprint=res["overlap_footprint"], metrics=res["metrics"],
                       grounding=res["grounding"], items=len(res["lists"]["A"]))
        else:
            out.update(summary=res["summary"], notes=res["notes"], grounding=res["grounding"],
                       bridges=len(res["bridges"]), swaps=len(res["swaps"]),
                       stops=[{"name": res["cards"][s["id"]]["name"], "category": s["category"],
                               "affinity": res["cards"][s["id"]]["affinity"], "km": res["cards"][s["id"]]["distance_km"],
                               "links": [l["name"] for l in res["cards"][s["id"]]["taste_links"]][:2],
                               "signals": res["cards"][s["id"]]["signals"], "tags": res["cards"][s["id"]]["tags"][:6],
                               "has_image": bool(res["cards"][s["id"]]["image_url"])}
                              for d in res["days"] for s in d["stops"]])
        return out

    if STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(STATIC / "index.html")

    return app


app = create_app()
