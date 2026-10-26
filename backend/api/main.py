"""API server entry point.

Design doc 6.1 architecture: frontend -> local backend -> {pipeline, models(DB)}
Run: uvicorn api.main:app --reload  (binds 127.0.0.1 unless told otherwise; keep it so)
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.episodes import router as episodes_router
from api.events import router as events_router
from api.novels import router as novels_router
from api.relations import router as relations_router
from api.settings import router as settings_router
from models.db import check_database

# With no accounts, these keep a web page open in the author's browser from
# using this API (design doc 10.4.2):
# - only these Host names are served, so a site whose DNS name is pointed at
#   127.0.0.1 (DNS rebinding) is refused;
# - every request must carry CLIENT_HEADER, which the app's own frontend sends
#   (api/client.ts). A page on another site can't: a custom header needs a CORS
#   preflight this API never approves, and what needs none (a form, an <img>,
#   a link) can't set it. The desktop shell will make its value a per-launch
#   secret, for programs on the PC too.
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
CLIENT_HEADER = "X-Retcona-Client"
# Read-only and changing nothing: the liveness check and FastAPI's API docs.
_OPEN_PATHS = frozenset(("/health", "/docs", "/redoc", "/openapi.json"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Blocking DB work, off the event loop (nothing else is being served yet,
    # but this still shouldn't set the precedent of blocking it from
    # lifespan).
    await asyncio.to_thread(check_database)
    yield


app = FastAPI(title="Retcona API", lifespan=lifespan)


def _openapi() -> dict:
    # The docs (/docs) list the header as the API's key, so "Authorize" there
    # (any value) lets "Try it out" through.
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schema.setdefault("components", {})["securitySchemes"] = {
            "client": {"type": "apiKey", "in": "header", "name": CLIENT_HEADER}
        }
        schema["security"] = [{"client": []}]
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _openapi


@app.middleware("http")
async def require_client_header(request: Request, call_next):
    if request.url.path not in _OPEN_PATHS and not request.headers.get(CLIENT_HEADER):
        return JSONResponse({"detail": f"Missing {CLIENT_HEADER} header"}, status_code=403)
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
