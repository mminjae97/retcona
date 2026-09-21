"""API server entry point.

Design doc 6.1 architecture: frontend -> API server -> {auth, pipeline, models(DB)}
Run: uvicorn api.main:app --reload
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from api.episodes import router as episodes_router
from api.novels import router as novels_router
from auth.jwe import validate_keys
from auth.router import router as auth_router
from workers.purge import purge_once, seconds_until_next_midnight

# uvicorn only sets up handlers for its own loggers, so this one is used to have
# the purge's INFO line show up next to the server's own output.
logger = logging.getLogger("uvicorn.error")

# The API server purges accounts past their deletion grace period (3.5) every
# day at midnight (PURGE_TIMEZONE, see workers/purge.py). Set this to 0 to turn
# that off, e.g. when a separate worker or scheduler does it.
PURGE_ENABLED_ENV = "PURGE_ENABLED"
_FALSE_VALUES = {"0", "false", "no", "off"}


def _purge_enabled() -> bool:
    return os.environ.get(PURGE_ENABLED_ENV, "1").strip().lower() not in _FALSE_VALUES


async def _purge_daily() -> None:
    while True:
        await asyncio.sleep(seconds_until_next_midnight())
        try:
            # Blocking DB work, off the event loop. Safe alongside other
            # instances running the same loop: see workers/purge.py.
            result = await asyncio.to_thread(purge_once)
            if result.purged:
                logger.info("Purged %d account(s) past the deletion grace period", result.purged)
        except Exception:
            logger.exception("Account purge pass failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_keys()
    purge_task = None
    if _purge_enabled():
        seconds_until_next_midnight()  # a bad PURGE_TIMEZONE fails startup, not the first midnight
        purge_task = asyncio.create_task(_purge_daily())
    yield
    if purge_task is not None:
        purge_task.cancel()
        with suppress(asyncio.CancelledError):
            await purge_task


app = FastAPI(title="Retcona API", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(novels_router, prefix="/novels", tags=["novels"])
app.include_router(episodes_router, prefix="/novels", tags=["episodes"])

# TODO: register remaining routers (design doc 2.4 validation results, etc.)
