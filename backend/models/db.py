"""DB engine/session.

Changing only DATABASE_URL should be enough to switch between local (e2-micro)
and Cloud SQL (10.5.4).
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://retcona:retcona@localhost:5432/retcona")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
