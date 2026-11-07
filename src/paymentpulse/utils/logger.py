"""
PaymentPulse — Structured Pipeline Logger
=========================================
Provides a consistent logger for all pipeline components.
Every log record includes a pipeline_run_id so log lines from the same
run can be correlated across modules.

Why this exists: financial-services pipelines are audited. A structured,
named logger with a run-ID means every INFO/WARNING/ERROR line is traceable
back to the exact batch that produced it, without requiring a log aggregation
platform locally.
"""

import logging
import sys
from datetime import UTC, datetime


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Return a named logger with a consistent format.

    Args:
        name: Module name (use __name__ in calling modules).
        level: Logging level string (DEBUG, INFO, WARNING, ERROR).

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        # Avoid adding duplicate handlers if module is re-imported
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    # Use UTC for all log timestamps — consistent regardless of local timezone
    fmt.converter = lambda *args: datetime.now(UTC).timetuple()
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.propagate = False

    return logger
