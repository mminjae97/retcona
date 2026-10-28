"""Common Base, column types and the multi-tenancy (per-novel isolation) mixin.

Design doc 10.1: every read/write must be filtered by novel_id.
Models that inherit NovelScopedMixin below get a novel_id column.
Repository functions should likewise take novel_id as a required argument (6.2).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect, ForeignKey, TypeDecorator, Uuid, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.functions import now


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
    """A point in time. SQLite has no timestamp type: it's kept as text in UTC
    with no zone ("2026-10-28 09:15:02.123456", which sorts and compares in
    time order), so a value going in is converted to UTC — a naive one is
    refused, its zone unknown — and one coming out is read as UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"A datetime with no time zone: {value!r}")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    """Now, to the microsecond: what a row's own times are set to from Python
    (TimestampMixin, Episode.updated_at), finer than SQLite's clock — two
    saves in one millisecond still differ."""
    return datetime.now(UTC)


@compiles(now, "sqlite")
def _now_on_sqlite(element: now, compiler, **kw) -> str:
    # SQLite's CURRENT_TIMESTAMP has whole seconds, so two saves in one second
    # would look the same (validation results go out of date by updated_at).
    # Milliseconds, the most SQLite's clock gives, padded to UtcDateTime's
    # six digits: the text compares with what Python writes. For a time set in
    # an UPDATE (finished_at) and a row inserted outside the models; the
    # models set their own times from Python (utcnow), to the microsecond.
    return "strftime('%Y-%m-%d %H:%M:%f000', 'now')"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, server_default=func.now())


class NovelScopedMixin:
    """Every table inheriting this mixin has a required novel_id FK (4.1, 10.1).
    Deleting the novel deletes its rows (the trash, pipeline/empty_trash.py)."""

    novel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True
    )
