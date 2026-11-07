"""Logging configuration."""

import logging
import sys
from typing import Any

import structlog
from loguru import logger


# HTTP client libraries log full request URLs at INFO/DEBUG. Meta Graph OAuth
# exchanges and token inspection carry the app access token, client secret or
# authorization code in the query string, so these loggers never go below
# WARNING whatever the root level is (FR-23 log-leakage hardening).
URL_LOGGING_LIBRARIES = ("httpx", "httpcore", "urllib3", "botocore", "hpack")


def quiet_url_logging() -> None:
    for name in URL_LOGGING_LIBRARIES:
        library_logger = logging.getLogger(name)
        if library_logger.level < logging.WARNING:
            library_logger.setLevel(logging.WARNING)


def setup_logging():
    """Configure structured logging."""
    quiet_url_logging()
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure loguru
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )


def get_logger(name: str) -> Any:
    """Get a logger instance."""
    return structlog.get_logger(name)
