"""Log output for this app's own packages (api, auth, models, workers, ...).

Nothing else sets it up: uvicorn only configures its own loggers, so a module
logger here (logging.getLogger(__name__)) would have no handler. Its warnings
would then reach stderr through Python's last-resort handler as a bare message
(no level, no logger name, so `grep WARNING` misses them), and anything below
WARNING would be dropped.

Called from api/__init__.py and workers/__init__.py, i.e. before any module in
those packages is imported, because some of what they import logs at import
time (models.nickname_rules warns about a bad shared/nickname-rules.json).
"""

import logging

from uvicorn.logging import DefaultFormatter

# The top-level packages in pyproject.toml's [tool.setuptools.packages.find]
# include — keep the two in sync: a package missing here logs only WARNING and
# up, through whatever the root logger has.
APP_PACKAGES = ("ai", "api", "auth", "infra", "models", "pipeline", "workers")


def _app_log_level() -> int:
    # uvicorn sets its own loggers' level from --log-level (uvicorn.error is
    # what this app's logs used to go through), before it imports the app;
    # follow it. NOTSET when uvicorn isn't the entry point (the standalone
    # purge worker), which gets INFO.
    level = logging.getLogger("uvicorn.error").level
    return level if level != logging.NOTSET else logging.INFO


def configure_app_logging() -> None:
    root = logging.getLogger()
    # Output goes through the root logger, and only gets a handler of its own
    # when nothing configured one — a deployment's own root setup (a JSON
    # formatter via --log-config, the Cloud Logging handler, pytest's caplog)
    # keeps receiving everything. uvicorn's own loggers don't propagate to
    # root, so nothing prints twice; and a later basicConfig() (the standalone
    # purge worker) is a no-op once root has this handler.
    if not root.handlers:
        handler = logging.StreamHandler()
        # uvicorn's own formatter, so these lines look like the server's own
        # ("WARNING:  models.db: ...").
        handler.setFormatter(DefaultFormatter("%(levelprefix)s %(name)s: %(message)s"))
        root.addHandler(handler)
    # Only this app's packages are lowered to the app level; everything else
    # keeps the root's (WARNING by default), so library INFO chatter stays out.
    level = _app_log_level()
    for name in APP_PACKAGES:
        logging.getLogger(name).setLevel(level)
