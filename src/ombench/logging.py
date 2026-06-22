"""Lightweight logging setup built on the standard library and rich.

The platform uses a single named logger ``ombench``. Output goes through rich for
readable console formatting when available, falling back to plain stderr.
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False


def get_logger(name: str = "ombench") -> logging.Logger:
    """Return a configured logger.

    The log level is read once from ``OMBENCH_LOG_LEVEL`` (default ``INFO``). A
    rich handler is used when the dependency is importable, otherwise a plain
    stream handler. Configuration is idempotent.
    """
    global _CONFIGURED
    logger = logging.getLogger("ombench")
    if not _CONFIGURED:
        level_name = os.environ.get("OMBENCH_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        logger.setLevel(level)
        handler: logging.Handler
        try:
            from rich.logging import RichHandler

            handler = RichHandler(rich_tracebacks=True, show_path=False)
            handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
        except Exception:  # pragma: no cover - fallback path
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
        logger.addHandler(handler)
        logger.propagate = False
        _CONFIGURED = True

    if name == "ombench":
        return logger
    return logger.getChild(name)
