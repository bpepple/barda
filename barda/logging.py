"""Logging module"""

import logging
from logging import basicConfig

from barda.utils import get_settings_folder

DATE_FMT = "%Y-%m-%d %H:%M:%S %Z"
LOG_FMT = "{asctime} {levelname:8} {message}"


def init_logging():
    """Initializing logging"""
    formatter = logging.Formatter(LOG_FMT, style="{", datefmt=DATE_FMT)
    log_path = get_settings_folder() / "barda.log"
    handler = logging.FileHandler(str(log_path))
    handler.setFormatter(formatter)
    basicConfig(level=logging.WARNING, handlers=[handler])
