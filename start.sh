#!/bin/bash

# start.sh

set -e

# Initialize PostgreSQL (only if data directory is empty)
if [ ! -d "/var/lib/postgresql/data" ]; then
  echo "Initializing PostgreSQL..."
  sudo -u postgres /usr/lib/postgresql/14/bin/initdb -D /var/lib/postgresql/data --encoding=UTF8 --locale=C.UTF-8
fi

# Start PostgreSQL
echo "Starting PostgreSQL..."
sudo -u postgres /usr/lib/postgresql/14/bin/pg_ctl -D /var/lib/postgresql/data -l /var/log/postgresql/postgresql.log start

# Wait for PostgreSQL to be ready
PG_READY=0
for i in $(seq 1 10); do
  if sudo -u postgres pg_isready -h localhost -p 5432 -U pg; then
    PG_READY=1
    break
  fi
  echo "Waiting for PostgreSQL to start... ($i/10)"
  sleep 1
done

if [ "$PG_READY" -eq 0 ]; then
  echo "PostgreSQL did not start in time. Exiting."
  exit 1
fi

# Start Uvicorn (your FastAPI application)
echo "Starting Uvicorn..."
exec uvicorn lumina.web.api:app --host 0.0.0.0 --port 8000