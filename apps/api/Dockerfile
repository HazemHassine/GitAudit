# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /build

# Create isolated virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Efficient caching: install dependencies before copying full application code
COPY pyproject.toml ./
RUN mkdir -p src/maintainer_api && \
    touch src/maintainer_api/__init__.py && \
    pip install --no-cache-dir .

# Copy application source and install package without reinstalling dependencies
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

FROM python:3.12-slim AS runner

WORKDIR /app

# Minimal runtime dependencies: curl for healthcheck, git for repository operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy self-contained virtual environment
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Run as non-root user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/sh -m appuser

# Copy application files and migrations
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY src/ ./src/
COPY docker-entrypoint.sh ./

RUN chmod +x docker-entrypoint.sh && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/readyz || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "maintainer_api.main:app", "--host", "0.0.0.0", "--port", "8001"]

# Trusted orchestration worker alone receives access to the Docker daemon.
FROM runner AS worker
USER root
RUN apt-get update && apt-get install -y --no-install-recommends docker.io && \
    rm -rf /var/lib/apt/lists/*
USER appuser
ENTRYPOINT []
CMD ["python", "-m", "maintainer_api.audit_worker"]
