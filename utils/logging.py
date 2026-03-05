"""Logging configuration for the viewer application."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Path] = None,
    fmt: str = "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt: str = "%H:%M:%S",
) -> None:
    """
    Configure the root logger.

    :param level:    Minimum log level (e.g. logging.DEBUG).
    :param log_file: Optional path to write logs to a file.
    :param fmt:      Log format string.
    :param datefmt:  Date/time format.
    """
    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(fmt, datefmt=datefmt)

    # Console handler
    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    # File handler (optional)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    # Silence noisy third-party loggers.
    # NOTE: "astropy" is intentionally excluded — pre-creating that logger
    # before astropy initialises its AstroLogger class causes AttributeError
    # ('Logger' object has no attribute '_set_defaults').
    # Astropy manages its own log level internally.
    for name in ("PIL", "rawpy", "psd_tools"):
        logging.getLogger(name).setLevel(logging.WARNING)
