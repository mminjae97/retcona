# db

Uses Alembic as the schema migration tool (design doc 10.5.4) — adopted from the start so local (e2-micro) and Cloud SQL stay identically reproducible.

## Usage

```bash
# with the backend virtualenv activated (alembic is a backend dependency)
cd db
alembic revision --autogenerate -m "description"
alembic upgrade head
```

`env.py` must import every model under `backend/models/` so they're registered on `Base.metadata`, so that autogenerate works correctly (TODO).

## e2-micro -> Cloud SQL migration (10.5.4)

Migrate using standard `pg_dump`/`pg_restore` (or logical replication). Only the `DATABASE_URL` value needs to change — no application code changes required.
