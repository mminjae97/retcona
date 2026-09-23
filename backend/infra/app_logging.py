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


class _LastResortHandler(logging.Handler):
    """What Python's own last-resort handler is — a write to sys.stderr as it
    is at that moment, not as it was at import time, so pytest's capture or
    anything else that swaps sys.stderr keeps getting these lines instead of a
    closed stream's "I/O operation on closed file" — plus uvicorn's formatting
    and a filter that lets the app's INFO through. A plain Handler, not a
    StreamHandler: there's no stream of its own to set (setStream)."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(DefaultFormatter("%(levelprefix)s %(name)s: %(message)s"))

    def filter(self, record: logging.LogRecord) -> bool:
        # Below WARNING only for the app's own packages. A library logger
        # someone lowered to DEBUG/INFO without giving it a handler stays as
        # quiet as Python's default last-resort handler (WARNING) keeps it.
        if record.levelno < logging.WARNING and record.name.split(".", 1)[0] not in APP_PACKAGES:
            return False
        return super().filter(record)

    terminator = "\n"

    def emit(self, record: logging.LogRecord) -> None:
        # StreamHandler.emit's, against the current sys.stderr: flushed per
        # record, so a crash right after a line doesn't leave it in a buffer.
        try:
            stream = sys.stderr
            stream.write(self.format(record) + self.terminator)
            stream.flush()
        except RecursionError:
            raise
        except Exception:  # noqa: BLE001 — the stdlib handlers' own pattern: handleError reports it
            self.handleError(record)


def _is_python_default(handler: logging.Handler | None) -> bool:
    # logging._defaultLastResort is the handler Python installs (in CPython
    # since 3.2, private but stable). Identity, not class: a separate
    # instance someone installed on purpose is theirs, not the default.
    return handler is not None and handler is getattr(logging, "_defaultLastResort", None)


def configure_app_logging() -> None:
    # Python's last-resort handler (what a record falls back to when neither
    # its logger nor any ancestor has a handler), replaced with one in
    # uvicorn's format ("WARNING:  models.db: ...") that also lets the app's
    # INFO lines through. Not a handler on the root logger: anything that sets
    # up root itself — a --log-config, logging.basicConfig, the Cloud Logging
    # handler, pytest's caplog — before or after this takes over completely,
    # with nothing printed twice. Only Python's own default is replaced: not
    # one someone else put there (even another stdlib handler), not None
    # (turned off on purpose), not ours (both entry packages call this).
    if _is_python_default(logging.lastResort):
        logging.lastResort = _LastResortHandler()
    # Only this app's packages are lowered to the app level; everything else
    # keeps the root's (WARNING by default), so library INFO chatter stays out.
    # A level a --log-config already set on one of them is left alone.
    level = _app_log_level()
    for name in APP_PACKAGES:
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET:
            logger.setLevel(level)
