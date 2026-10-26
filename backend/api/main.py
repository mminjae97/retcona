"""API server entry point.

Design doc 6.1 architecture: frontend -> local backend -> {pipeline, models(DB)}
Run: uvicorn api.main:app --reload
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.episodes import router as episodes_router
from api.events import router as events_router
from api.novels import router as novels_router
from api.relations import router as relations_router
from api.settings import router as settings_router
from models.db import check_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Blocking DB work, off the event loop (nothing else is being served yet,
    # but this still shouldn't set the precedent of blocking it from
    # lifespan).
    await asyncio.to_thread(check_database)
    yield


app = FastAPI(title="Retcona API", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(novels_router, prefix="/novels", tags=["novels"])
app.include_router(episodes_router, prefix="/novels", tags=["episodes"])
app.include_router(settings_router, prefix="/novels", tags=["settings"])
app.include_router(relations_router, prefix="/novels", tags=["relations"])
app.include_router(events_router, prefix="/novels", tags=["events"])

# TODO: register remaining routers (design doc 2.4 validation results, etc.)
