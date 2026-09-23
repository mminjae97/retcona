"""Import every model module so they register on Base.metadata (needed for Alembic autogenerate)."""

from models.base import Base
from models import (  # noqa: F401
    character,
    claim,
    email_verification,
    episode,
    location,
    novel,
    relation,
    story_event,
    user,
    validation_run,
    world_setting,
)

__all__ = ["Base"]
