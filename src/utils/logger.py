"""Logging setup shared by the application and future data modules."""

from __future__ import annotations

import logging
from pathlib import Path

from config.settings import LOG_DIR


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_FILE_NAME = "fpl_analyst.log"


def configure_logging(log_level: str = "INFO") -> None:
    """Configure console and file logging once per process."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    log_path = LOG_DIR / LOG_FILE_NAME
    has_file_handler = any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_path
        for handler in root_logger.handlers
    )

    if not has_file_handler:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(file_handler)

    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger after the default setup is available."""
    configure_logging()
    return logging.getLogger(name)
