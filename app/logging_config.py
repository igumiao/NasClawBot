"""Logging setup for local app runs and diagnostics."""

import logging


def configure_logging(log_level: str = "INFO") -> None:
    """Configure readable process-wide logging without duplicate handlers."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.setLevel(level)
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
