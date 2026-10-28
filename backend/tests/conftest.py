"""The tests' own database: a SQLite file in a temporary folder, migrated to
head once per test session — never the app's (models/db.py), which the
tests would fill with their novels and empty the trash of. Set before any
test module imports models.db, which reads DATABASE_URL then."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import URL

_DIR = Path(tempfile.mkdtemp(prefix="retcona-tests-"))
# Built, not pasted into a string, as models/db.py builds its own: a % in the
# temporary folder's path stays a %.
os.environ["DATABASE_URL"] = URL.create("sqlite", database=(_DIR / "retcona.db").as_posix()).render_as_string()


@pytest.fixture(scope="session", autouse=True)
def database():
    from models.db import engine, upgrade_database

    upgrade_database()
    yield
    engine.dispose()
    shutil.rmtree(_DIR, ignore_errors=True)
