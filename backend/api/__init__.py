# Before any module in this package (and, through it, models.*, which logs at
# import time) is imported — see infra/app_logging.py.
from infra.app_logging import configure_app_logging

configure_app_logging()
