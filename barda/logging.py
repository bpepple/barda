"""Logging module"""

import logging
from logging import basicConfig

DATEFMT = "%Y-%m-%d %H:%M:%S %Z"
LOG_FMT = "{asctime} {levelname:8} {message}"


def init_logging():
    """Initializing logging"""
    formatter = logging.Formatter(LOG_FMT, style="{", datefmt=DATEFMT)
    handler = logging.FileHandler("barda.log")
    handler.setFormatter(formatter)
    basicConfig(level=logging.WARNING, handlers=[handler])
