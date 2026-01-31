# Lumina Scripts

This directory contains operational and development scripts for Lumina.

## Production Scripts

### `start.sh`
**Purpose**: Container startup script
**Usage**: Automatically executed by Docker container on startup
**What it does**:
- Initializes PostgreSQL database
- Starts Redis server
- Launches Celery workers
- Starts FastAPI web server

**You don't need to run this manually** - it's called by the Docker container.

## Development Scripts

### `dev/run_local.sh`
**Purpose**: Run Lumina locally without Docker
**Usage**: For developers who want to run Lumina natively on their machine
**Prerequisites**:
- PostgreSQL installed and running locally
- Redis installed and running locally
- Python virtual environment activated
- See `docs/technical/DEVELOPMENT.md` for full setup

```bash
cd scripts/dev
./run_local.sh
```

## Historical Migrations

### `migrations/migrate_geohash.py`
**Purpose**: Historical database migration for geohash feature
**Status**: Completed migration, kept for reference
**Note**: Not needed for new installations

---

## Running Tests

Tests are run via pytest, not shell scripts:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=lumina --cov-report=html

# Run specific test file
pytest tests/core/test_catalog.py
```

See `docs/technical/DEVELOPMENT.md` for complete testing documentation.

---

## Need Help?

- **User documentation**: `docs/guides/USER_GUIDE.md`
- **Development setup**: `docs/technical/DEVELOPMENT.md`
- **Troubleshooting**: `docs/guides/TROUBLESHOOTING.md`
