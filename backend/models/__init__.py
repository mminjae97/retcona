"""Import every model module so they register on Base.metadata (needed for Alembic autogenerate)."""

from models.base import Base
from models import (  # noqa: F401
    character,
    claim_link_choice,
    claim,
    episode,
    flag_dismissal,
    flag_revalidation,
    job,
    location,
    novel,
    relation,
    story_event,
    validation_run,
    world_setting,
)

__all__ = ["Base"]
