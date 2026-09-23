"""Log output for this app's own packages (api, auth, models, workers, ...).

Nothing else sets it up: uvicorn only configures its own loggers, so a module
logger here (logging.getLogger(__name__)) would have no handler. Its warnings
would then reach stderr through Python's default last-resort handler as a bare
message (no level, no logger name, so `grep WARNING` misses them), and
anything below WARNING would be dropped.

Called from api/__init__.py and workers/__init__.py, i.e. before any module in
those packages is imported, because some of what they import logs at import
time (models.nickname_rules warns about a bad shared/nickname-rules.json).
"""

import logging
import sys

from uvicorn.logging import DefaultFormatter

# The top-level packages in pyproject.toml's [tool.setuptools.packages.find]
# include — keep the two in sync: a package missing here logs only WARNING and
# up.
APP_PACKAGES = ("ai", "api", "auth", "infra", "models", "pipeline", "workers")


def _app_log_level() -> int:
    # uvicorn sets its loggers' level from --log-level (uvicorn.error is what
    # this app's logs used to go through) before it imports the app; follow
    # it. Effective level, so a level a --log-config put on the parent
    # "uvicorn" logger counts too. When uvicorn configured nothing (the
    # standalone purge worker; or gunicorn --preload, which imports the app
    # before its workers set the level), INFO.
    uvicorn_error = logging.getLogger("uvicorn.error")
    configured = any(
        logger.level != logging.NOTSET for logger in (uvicorn_error, logging.getLogger("uvicorn"))
    )
    return uvicorn_error.getEffectiveLevel() if configured else logging.INFO


class _LastResortHandler(logging.StreamHandler):
    """What Python's own last-resort handler is, plus uvicorn's formatting and
    a level filter that lets the app's INFO through."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)
        self.setFormatter(DefaultFormatter("%(levelprefix)s %(name)s: %(message)s"))

    @property
    def stream(self):
        # sys.stderr as it is now, not as it was at import time (which
        # StreamHandler would hold on to): pytest's capture, or anything else
        # that swaps sys.stderr, keeps getting these lines instead of a
        # closed stream's "I/O operation on closed file".
        return sys.stderr

    def filter(self, record: logging.LogRecord) -> bool:
        # Below WARNING only for the app's own packages. A library logger
        # someone lowered to DEBUG/INFO without giving it a handler stays as
        # quiet as Python's default last-resort handler (WARNING) keeps it.
        if record.levelno < logging.WARNING and record.name.split(".", 1)[0] not in APP_PACKAGES:
            return False
        return super().filter(record)


def configure_app_logging() -> None:
    # Python's last-resort handler (what a record falls back to when neither
    # its logger nor any ancestor has a handler), replaced with one in
    # uvicorn's format ("WARNING:  models.db: ...") that also lets the app's
    # INFO lines through. Not a handler on the root logger: anything that sets
    # up root itself — a --log-config, logging.basicConfig, the Cloud Logging
    # handler, pytest's caplog — before or after this takes over completely,
    # with nothing printed twice. Only Python's own is replaced: not one
    # someone else put there, not None (turned off on purpose), not ours
    # (both entry packages call this).
    if type(logging.lastResort).__module__ == "logging":
        logging.lastResort = _LastResortHandler()
    # Only this app's packages are lowered to the app level; everything else
    # keeps the root's (WARNING by default), so library INFO chatter stays out.
    # A level a --log-config already set on one of them is left alone.
    level = _app_log_level()
    for name in APP_PACKAGES:
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET:
            logger.setLevel(level)
