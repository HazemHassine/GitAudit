#!/bin/sh
set -e

# Run database migrations before starting the API service
alembic -c alembic.ini upgrade head

# Exec child process so it replaces PID 1 and receives SIGTERM/SIGINT signals directly
exec "$@"
