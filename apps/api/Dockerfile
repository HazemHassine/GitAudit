FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy application code and migrations
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY src/ ./src/

# Install package in editable mode so changes and entry points are linked
RUN pip install --no-cache-dir --no-deps -e .

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["sh", "-c", "alembic -c alembic.ini upgrade head && uvicorn maintainer_api.main:app --host 0.0.0.0 --port 8001"]
