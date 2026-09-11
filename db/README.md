# db

스키마 마이그레이션 도구로 Alembic을 사용합니다 (설계서 10.5.4) — 로컬(e2-micro)과 Cloud SQL 양쪽에서 동일하게 재현 가능하도록 처음부터 도입합니다.

## 사용법

```bash
# backend 가상환경이 활성화된 상태에서 (alembic은 backend의 의존성)
cd db
alembic revision --autogenerate -m "설명"
alembic upgrade head
```

`env.py`는 `backend/models/`의 모든 모델을 `Base.metadata`에 등록된 상태로 임포트해 autogenerate가 동작하도록 구성해야 합니다 (TODO).

## e2-micro -> Cloud SQL 전환 (10.5.4)

표준 `pg_dump`/`pg_restore`(또는 논리적 복제)로 이전합니다. `DATABASE_URL` 값만 바꾸면 애플리케이션 코드는 변경할 필요가 없습니다.
