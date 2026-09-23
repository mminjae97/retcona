# db

Uses Alembic as the schema migration tool (design doc 10.5.4) — adopted from the start so local (e2-micro) and Cloud SQL stay identically reproducible.

## Usage

```bash
# with the backend virtualenv activated (alembic is a backend dependency)
cd db
alembic revision --autogenerate -m "description"
alembic upgrade head
```

The API server checks at startup that the database is at this directory's head and refuses to start if it's behind (see `backend/README.md`, "Startup checks"), so run `alembic upgrade head` before starting a release that adds a migration.

`env.py` imports `backend/models/__init__.py`, which in turn imports every model module so they're registered on `Base.metadata` before autogenerate runs.

## e2-micro -> Cloud SQL migration (10.5.4)

Migrate using standard `pg_dump`/`pg_restore` (or logical replication). Only the `DATABASE_URL` value needs to change — no application code changes required.
