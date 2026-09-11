"""Alembic 환경 설정.

DATABASE_URL 환경변수를 그대로 사용해 로컬/Cloud SQL 전환이 코드 변경 없이 되도록 한다 (10.5.4).
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# TODO: backend/models/의 모든 모델 모듈을 임포트해 Base.metadata에 등록되게 할 것
# from models.base import Base
# from models import user, novel, character, location, world_setting, episode, claim, relation, story_event
# target_metadata = Base.metadata
target_metadata = None

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
