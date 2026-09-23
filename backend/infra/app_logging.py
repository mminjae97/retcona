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


def configure_app_logging() -> None:
    # Python's last-resort handler (what a record falls back to when neither
    # its logger nor any ancestor has a handler), with uvicorn's formatter so
    # these lines look like the server's own ("WARNING:  models.db: ..."), and
    # no level of its own, so the app's INFO lines get through too. Not a
    # handler on the root logger: anything that sets up root itself — a
    # --log-config, logging.basicConfig, the Cloud Logging handler, pytest's
    # caplog — before or after this takes over completely, with nothing
    # printed twice.
    if isinstance(logging.lastResort, logging.StreamHandler) and not getattr(
        logging.lastResort, "_app_logging", False
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(DefaultFormatter("%(levelprefix)s %(name)s: %(message)s"))
        handler._app_logging = True  # both entry packages call this
        logging.lastResort = handler
    # Only this app's packages are lowered to the app level; everything else
    # keeps the root's (WARNING by default), so library INFO chatter stays out.
    # A level a --log-config already set on one of them is left alone.
    level = _app_log_level()
    for name in APP_PACKAGES:
        logger = logging.getLogger(name)
        if logger.level == logging.NOTSET:
            logger.setLevel(level)
