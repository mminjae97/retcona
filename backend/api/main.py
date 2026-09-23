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
from models.db import check_database
from workers.purge import (
    PASS_RETRY_SECONDS,
    delay_after_pass,
    purge_pass,
    seconds_until_next_midnight,
)

logger = logging.getLogger(__name__)

# The API server purges accounts past their deletion grace period (3.5) every
# day at midnight (PURGE_TIMEZONE, see workers/purge.py). Set this to 0 to turn
# that off, e.g. when a separate worker or scheduler does it.
PURGE_ENABLED_ENV = "PURGE_ENABLED"
_FALSE_VALUES = {"0", "false", "no", "off"}


def _purge_enabled() -> bool:
    return os.environ.get(PURGE_ENABLED_ENV, "1").strip().lower() not in _FALSE_VALUES


# Let startup (migrations, warm-up) settle before the catch-up pass.
PURGE_STARTUP_DELAY_SECONDS = 60.0


async def _purge_daily() -> None:
    delay = PURGE_STARTUP_DELAY_SECONDS
    while True:
        try:
            await asyncio.sleep(delay)
            # Blocking DB work, off the event loop. Safe alongside other
            # instances running the same loop: see workers/purge.py. The pass
            # and what comes after it (the next midnight, or a retry after a
            # failed pass) are the standalone worker's too.
            delay = delay_after_pass(await asyncio.to_thread(purge_pass))
        except Exception:
            # Anything that would end this task (it is only awaited at shutdown,
            # so it would die unnoticed and the purge never run again) — e.g.
            # working out the next midnight failing.
            logger.exception("Account purge schedule failed")
            delay = PASS_RETRY_SECONDS


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_keys()
    # Blocking DB work, off the event loop (nothing else is being served yet,
    # but this still shouldn't set the precedent of blocking it from
    # lifespan) — same reasoning as the purge pass below.
    await asyncio.to_thread(check_database)
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
