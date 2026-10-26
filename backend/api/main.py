"""API server entry point.

Design doc 6.1 architecture: frontend -> local backend -> {pipeline, models(DB)}
Run: uvicorn api.main:app --reload  (binds 127.0.0.1 unless told otherwise; keep it so)
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.episodes import router as episodes_router
from api.events import router as events_router
from api.novels import router as novels_router
from api.relations import router as relations_router
from api.settings import router as settings_router
from models.db import check_database

# With no accounts, where a request comes from is what keeps a web page open in
# the author's browser from using this API (design doc 10.4.2). The per-launch
# secret the desktop shell will pass comes with the shell; until then:
# - only these Host names are served, so a site whose DNS name is pointed at
#   127.0.0.1 (DNS rebinding) is refused;
# - a browser request whose Origin isn't the app's own is refused, so another
#   site can't send one (CSRF).
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
# Comma-separated; the frontend's origin (Vite's dev server by default).
ALLOWED_ORIGINS_ENV = "ALLOWED_ORIGINS"
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def _allowed_origins() -> frozenset[str]:
    value = os.environ.get(ALLOWED_ORIGINS_ENV, DEFAULT_ALLOWED_ORIGINS)
    return frozenset(origin.strip().rstrip("/") for origin in value.split(",") if origin.strip())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Blocking DB work, off the event loop (nothing else is being served yet,
    # but this still shouldn't set the precedent of blocking it from
    # lifespan).
    await asyncio.to_thread(check_database)
    yield


app = FastAPI(title="Retcona API", lifespan=lifespan)

_ORIGINS = _allowed_origins()


@app.middleware("http")
async def reject_foreign_origin(request: Request, call_next):
    # No Origin: not a cross-site browser request (a same-origin GET, or a
    # program on this PC, which the shell's secret is for).
    origin = request.headers.get("origin")
    if origin is not None and origin not in _ORIGINS:
        return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    return await call_next(request)


# Added last, so it runs first.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(novels_router, prefix="/novels", tags=["novels"])
app.include_router(episodes_router, prefix="/novels", tags=["episodes"])
app.include_router(settings_router, prefix="/novels", tags=["settings"])
app.include_router(relations_router, prefix="/novels", tags=["relations"])
app.include_router(events_router, prefix="/novels", tags=["events"])

# TODO: register remaining routers (design doc 2.4 validation results, etc.)
