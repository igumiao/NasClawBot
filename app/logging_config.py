"""Logging setup for local app runs and diagnostics."""

import logging


class _SuppressPollingAccessLogs(logging.Filter):
    """Drop uvicorn.access INFO logs for high-frequency polling endpoints."""

    _NOISY_PREFIXES = ("/task-events", "/health")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for prefix in self._NOISY_PREFIXES:
            if prefix in msg:
                return False
        return True


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

    # Silence uvicorn.access for high-frequency polling endpoints.
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.addFilter(_SuppressPollingAccessLogs())
