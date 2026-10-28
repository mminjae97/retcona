# db

Uses Alembic as the schema migration tool (design doc 10.5.4), on the app's SQLite database (`backend/models/db.py`). The API server applies the migrations itself at startup — it creates the database on the first start, and upgrades it (after copying it aside) when a new version adds migrations — so running them by hand is only needed to write a new one.

## Usage

```bash
# with the backend virtualenv activated (alembic is a backend dependency)
cd db
alembic revision --autogenerate -m "description"
alembic upgrade head
```

`alembic` works on the app's database, or the one `DATABASE_URL` names. Migrations are written in batch mode (`render_as_batch`), as SQLite can't alter most of a table in place; a hand-written one uses `op.batch_alter_table` the same way. They run with foreign keys off (a batch rebuild drops and recreates tables, which would otherwise cascade), checked with `PRAGMA foreign_key_check` before the transaction commits. A new foreign key needs `ondelete="CASCADE"` (`tests/test_trash_db.py` checks it).

`env.py` imports `backend/models/__init__.py`, which in turn imports every model module so they're registered on `Base.metadata` before autogenerate runs.
