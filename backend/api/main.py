"""API server entry point.

Design doc 6.1 architecture: frontend -> API server -> {auth, pipeline, models(DB)}
Run: uvicorn api.main:app --reload
"""

from fastapi import FastAPI

from auth.router import router as auth_router

app = FastAPI(title="Retcona API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth_router, prefix="/auth", tags=["auth"])

# TODO: register remaining routers (design doc 2.2 editor, 2.4 validation results, etc.)
