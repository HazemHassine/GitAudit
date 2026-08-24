import logging
import sys

import structlog
from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "maintainer_http_requests_total",
    "HTTP requests handled by the API",
    ("method", "path", "status"),
)
HTTP_DURATION = Histogram(
    "maintainer_http_request_duration_seconds",
    "HTTP request duration",
    ("method", "path"),
)
SCAN_TOTAL = Counter(
    "maintainer_repository_scans_total",
    "Repository scan outcomes",
    ("status",),
)
SCAN_DURATION = Histogram(
    "maintainer_repository_scan_duration_seconds",
    "Repository scan duration",
)


def configure_logging(level: str) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    # Third-party HTTP/DB libraries otherwise emit unstructured request lines and can
    # overwhelm scan logs. Application events retain sanitized source/error summaries.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
