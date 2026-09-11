"""Import every model module so they register on Base.metadata (needed for Alembic autogenerate)."""

from models.base import Base
from models import (  # noqa: F401
    character,
    claim,
    episode,
    location,
    novel,
    relation,
    story_event,
    user,
    world_setting,
)

__all__ = ["Base"]
