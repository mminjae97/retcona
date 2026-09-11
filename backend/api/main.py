"""API server entry point.

Design doc 6.1 architecture: frontend -> API server -> {auth, pipeline, models(DB)}
Run: uvicorn api.main:app --reload
"""

from fastapi import FastAPI

app = FastAPI(title="Retcona API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# TODO: register routers (endpoints matching design doc chapter 3 auth, 2.2 editor, 2.4 validation results, etc.)
# from auth.router import router as auth_router
# app.include_router(auth_router, prefix="/auth")
