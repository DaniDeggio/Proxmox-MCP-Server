"""Structured logging setup using structlog.

Provides two output modes:
- ``console``: colourful, human-friendly logs for development
- ``json``: machine-parseable JSON lines for production
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(level: str = "INFO", fmt: str = "console") -> structlog.stdlib.BoundLogger:
    """Configure structlog and the stdlib root logger.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR).
        fmt: Output format — ``"console"`` or ``"json"``.

    Returns:
        A bound logger ready for use.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if fmt == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Silence noisy third-party loggers
    for name in ("httpx", "httpcore", "paramiko", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

    from typing import cast
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger("deggio_infra_mcp"))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, optionally with a sub-name."""
    from typing import cast
    if name:
        return cast("structlog.stdlib.BoundLogger", structlog.get_logger(f"deggio_infra_mcp.{name}"))
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger("deggio_infra_mcp"))
