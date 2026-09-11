"""DB 엔진/세션.

DATABASE_URL 하나만 바꾸면 로컬(e2-micro) <-> Cloud SQL 전환이 가능하도록 한다 (10.5.4).
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://retcona:retcona@localhost:5432/retcona")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
