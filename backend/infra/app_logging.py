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

APP_PACKAGES = ("ai", "api", "auth", "infra", "models", "pipeline", "workers")


def configure_app_logging(level: int = logging.INFO) -> None:
    # uvicorn's own formatter, so these lines look like the server's own
    # ("WARNING:  models.db: ...").
    handler = logging.StreamHandler()
    handler.setFormatter(DefaultFormatter("%(levelprefix)s %(name)s: %(message)s"))
    for name in APP_PACKAGES:
        logger = logging.getLogger(name)
        if logger.handlers:  # already configured (both entry packages call this)
            continue
        logger.addHandler(handler)
        logger.setLevel(level)
        # Not also through the root logger: a root handler added later (e.g.
        # workers.purge's basicConfig for third-party loggers) would print
        # every line twice.
        logger.propagate = False
