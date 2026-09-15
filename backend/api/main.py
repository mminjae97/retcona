"""API server entry point.

Design doc 6.1 architecture: frontend -> API server -> {auth, pipeline, models(DB)}
Run: uvicorn api.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.novels import router as novels_router
from auth.jwe import validate_keys
from auth.router import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_keys()
    yield


app = FastAPI(title="Retcona API", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(novels_router, prefix="/novels", tags=["novels"])

# TODO: register remaining routers (design doc 2.2 editor, 2.4 validation results, etc.)
