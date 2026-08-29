"""Logging setup for CAD Knowledge Base."""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

import colorlog

from src.core.config import get_config


def _default_log_file() -> str:
    """Pick a log file name based on the running entrypoint.

    This prevents multiple long-running processes (API, GUI, watch_entry)
    from contending for the same cadkb.log and failing rotation.
    """
    cmd = " ".join(sys.argv).lower()
    if "serve" in cmd or "src.cli.main" in cmd and ("api" in cmd or "serve" in cmd):
        return "api.log"
    if "streamlit" in cmd or "src/gui/app.py" in cmd:
        return "gui.log"
    if "watch_entry" in cmd:
        return "watch_entry.log"
    return "cadkb.log"


def setup_logger(name: str = "cadkb") -> logging.Logger:
    """Set up and return a logger with console + file handlers."""
    config = get_config()
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Already configured

    logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    # Console handler with color
    console_handler = logging.StreamHandler()
    console_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt=config.log_date_format,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler
    if config.log_file_enabled:
        config.logs_dir.mkdir(parents=True, exist_ok=True)
        # CADKB_LOG_FILE allows tests to use a separate log file.
        # Default filename is chosen by entrypoint to avoid rotation conflicts
        # when API, GUI and watch_entry run concurrently.
        log_name = os.environ.get("CADKB_LOG_FILE", _default_log_file())
        log_file = config.logs_dir / log_name
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_formatter = logging.Formatter(
            config.log_format, datefmt=config.log_date_format
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger
