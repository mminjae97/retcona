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
from workers.purge import purge_once

logger = logging.getLogger(__name__)

# How often the API server purges accounts past their deletion grace period
# (3.5); 0 turns it off (e.g. when a separate worker or scheduler does it).
PURGE_INTERVAL_ENV = "PURGE_INTERVAL_SECONDS"
DEFAULT_PURGE_INTERVAL_SECONDS = 6 * 60 * 60
# Let startup (migrations, warm-up) settle before the first pass.
PURGE_STARTUP_DELAY_SECONDS = 60.0


async def _purge_periodically(interval: float, startup_delay: float = PURGE_STARTUP_DELAY_SECONDS) -> None:
    await asyncio.sleep(startup_delay)
    while True:
        try:
            # Blocking DB work, off the event loop. Safe alongside other
            # instances running the same loop: see workers/purge.py.
            purged = await asyncio.to_thread(purge_once)
            if purged:
                logger.info("Purged %d account(s) past the deletion grace period", purged)
        except Exception:
            logger.exception("Account purge pass failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_keys()
    interval = float(os.environ.get(PURGE_INTERVAL_ENV, DEFAULT_PURGE_INTERVAL_SECONDS))  # a bad value fails startup
    purge_task = asyncio.create_task(_purge_periodically(interval)) if interval > 0 else None
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
