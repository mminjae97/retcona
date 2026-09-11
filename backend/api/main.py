"""API 서버 엔트리포인트.

설계서 6.1 아키텍처: 프론트엔드 -> API 서버 -> {auth, pipeline, models(DB)}
실행: uvicorn api.main:app --reload
"""

from fastapi import FastAPI

app = FastAPI(title="Retcona API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# TODO: 라우터 등록 (설계서 3장 인증, 2.2 에디터, 2.4 검증 결과 등에 대응하는 엔드포인트)
# from auth.router import router as auth_router
# app.include_router(auth_router, prefix="/auth")
