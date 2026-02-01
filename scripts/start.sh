#!/bin/bash
set -e

# Set up log directory permissions
mkdir -p /var/log/postgresql
chown -R postgres:postgres /var/log/postgresql

# Initialize PostgreSQL data directory if it's not initialized
if [ ! -f "/var/lib/postgresql/14/main/postgresql.conf" ]; then
    echo "Initializing PostgreSQL database..."
    # Clean the directory contents (not the directory itself, in case it's a mount point)
    rm -rf /var/lib/postgresql/14/main/*
    rm -rf /var/lib/postgresql/14/main/.[!.]*
    chown -R postgres:postgres /var/lib/postgresql

    su - postgres -c "/usr/lib/postgresql/14/bin/initdb -D /var/lib/postgresql/14/main" 2>&1

    # Configure PostgreSQL
    echo "host all all 127.0.0.1/32 md5" >> /var/lib/postgresql/14/main/pg_hba.conf
    echo "host all all ::1/128 md5" >> /var/lib/postgresql/14/main/pg_hba.conf
    echo "local all all md5" >> /var/lib/postgresql/14/main/pg_hba.conf
fi

# Remove stale PID file from previous container run (PIDs don't persist across containers)
if [ -f "/var/lib/postgresql/14/main/postmaster.pid" ]; then
    echo "Removing stale postmaster.pid file..."
    rm -f /var/lib/postgresql/14/main/postmaster.pid
fi

# Start PostgreSQL as postgres user (with verbose output for debugging)
echo "Starting PostgreSQL..."
su - postgres -c "/usr/lib/postgresql/14/bin/postgres -D /var/lib/postgresql/14/main" &
POSTGRES_PID=$!
echo "PostgreSQL started with PID: $POSTGRES_PID"

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to start..."
until su - postgres -c "psql -U postgres -c 'SELECT 1' > /dev/null 2>&1"; do
  sleep 1
done

# Create user and database if they don't exist
echo "Setting up database..."
su - postgres -c "psql -U postgres -tc \"SELECT 1 FROM pg_user WHERE usename = 'pg'\" | grep -q 1 || psql -U postgres -c \"CREATE USER pg WITH SUPERUSER PASSWORD 'buffalo-jump';\""
su - postgres -c "psql -U postgres -tc \"SELECT 1 FROM pg_database WHERE datname = 'lumina'\" | grep -q 1 || psql -U postgres -c \"CREATE DATABASE lumina OWNER pg;\""

# Enable pgvector extension
echo "Enabling pgvector extension..."
su - postgres -c "psql -U postgres -d lumina -c 'CREATE EXTENSION IF NOT EXISTS vector;'"

echo "PostgreSQL is ready"

# Run database migrations if needed
cd /app

# Start the web application
echo "Starting Lumina web application..."
exec uvicorn lumina.web.api:app --host 0.0.0.0 --port 8000
