#!/bin/bash

# start.sh

set -e

# Initialize PostgreSQL (only if data directory is empty)
if [ ! -d "/var/lib/postgresql/data" ]; then
  echo "Initializing PostgreSQL..."
  sudo -u postgres /usr/lib/postgresql/14/bin/initdb -D /var/lib/postgresql/data
fi

# Start PostgreSQL
echo "Starting PostgreSQL..."
sudo -u postgres /usr/lib/postgresql/14/bin/pg_ctl -D /var/lib/postgresql/data -l /var/log/postgresql/postgresql.log start

# Start Uvicorn (your FastAPI application)
echo "Starting Uvicorn..."
uvicorn lumina.web.api:app --host 0.0.0.0 --port 8000