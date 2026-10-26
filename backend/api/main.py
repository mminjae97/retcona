"""API server entry point.

Design doc 6.1 architecture: frontend -> local backend -> {pipeline, models(DB)}
Run: uvicorn api.main:app --reload  (binds 127.0.0.1 unless told otherwise; keep it so)
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
# - every API route needs CLIENT_HEADER (an app-wide dependency, so a route added
#   later is covered too), which the app's own frontend sends (api/client.ts).
#   A page on another site can't: a custom header needs
#   a CORS preflight that neither this API nor the dev server's proxy approves,
#   and what needs none (a form, an <img>, a link) can't set it. The desktop
#   shell will make its value a per-launch secret, for programs on the PC too.
#   The API docs (/docs) list it as the API key: "Authorize" there, any value.
#   Not needed by the liveness check (/health) or the docs themselves, which
#   are plain routes and change nothing;
# - no page of this server may be framed (the docs could be clickjacked).
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
CLIENT_HEADER = "X-Retcona-Client"
_CLIENT = [Security(APIKeyHeader(name=CLIENT_HEADER))]
_NO_FRAMING = [(b"x-frame-options", b"DENY"), (b"content-security-policy", b"frame-ancestors 'none'")]


class NoFramingMiddleware:
    """Adds the no-framing headers to every response (plain ASGI: nothing else
    is wrapped)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *_NO_FRAMING]
            await send(message)

        await self.app(scope, receive, send_with_headers)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Blocking DB work, off the event loop (nothing else is being served yet,
    # but this still shouldn't set the precedent of blocking it from
    # lifespan).
    await asyncio.to_thread(check_database)
    yield


app = FastAPI(title="Retcona API", lifespan=lifespan, dependencies=_CLIENT)
app.add_middleware(NoFramingMiddleware)
# Added last, so it runs first.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# A plain route, outside the API (and its header): a liveness check.
app.add_route("/health", health, methods=["GET"])

app.include_router(novels_router, prefix="/novels", tags=["novels"])
app.include_router(episodes_router, prefix="/novels", tags=["episodes"])
app.include_router(settings_router, prefix="/novels", tags=["settings"])
app.include_router(relations_router, prefix="/novels", tags=["relations"])
app.include_router(events_router, prefix="/novels", tags=["events"])

# TODO: register remaining routers (design doc 2.4 validation results, etc.)
