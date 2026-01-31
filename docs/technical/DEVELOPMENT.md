# Development Guide

Guide for developers who want to contribute to Lumina or run it natively outside Docker.

## Development Setup (Native Python)

For developers who want to run Lumina directly on their machine without Docker.

### Prerequisites

- **Python 3.11+**
- **PostgreSQL 14+** installed and running
- **Redis** installed and running
- **ExifTool** for metadata extraction
- **Git** for version control

### Install Dependencies

#### PostgreSQL

**Ubuntu/Debian**:
```bash
sudo apt-get install postgresql postgresql-client
sudo systemctl start postgresql
```

**macOS (Homebrew)**:
```bash
brew install postgresql@14
brew services start postgresql@14
```

**Windows**:
Download from [postgresql.org](https://www.postgresql.org/download/windows/)

#### Redis

**Ubuntu/Debian**:
```bash
sudo apt-get install redis-server
sudo systemctl start redis
```

**macOS**:
```bash
brew install redis
brew services start redis
```

#### ExifTool

**Ubuntu/Debian**:
```bash
sudo apt-get install exiftool
```

**macOS**:
```bash
brew install exiftool
```

**Windows**:
Download from [exiftool.org](https://exiftool.org/)

### Clone and Setup

```bash
# Clone repository
git clone https://github.com/irjudson/lumina.git
cd lumina

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"
```

### Configure Database

```bash
# Create PostgreSQL database
createdb lumina

# Or with custom user:
sudo -u postgres createuser -P lumina
sudo -u postgres createdb -O lumina lumina
```

### Configure Environment

```bash
# Copy example
cp .env.example .env

# Edit .env
nano .env
```

Set for local development:
```bash
CATALOG_PATH=/path/to/dev/catalog
PHOTOS_PATH=/path/to/dev/photos

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=lumina
POSTGRES_USER=lumina
POSTGRES_PASSWORD=your-password

CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=db+postgresql://lumina:your-password@localhost:5432/lumina
```

### Run Services

You'll need 3 terminals:

**Terminal 1 - Celery Worker**:
```bash
source venv/bin/activate
celery -A lumina.celery_app worker --loglevel=info
```

**Terminal 2 - Web Server**:
```bash
source venv/bin/activate
lumina-web /path/to/catalog
```

**Terminal 3 - CLI Commands**:
```bash
source venv/bin/activate
lumina-analyze /path/to/catalog -s /path/to/photos
```

---

## Running Tests

### Quick Test Run

```bash
# Run all tests (parallel)
pytest

# Run without parallel execution
pytest -n 0

# Run specific test file
pytest tests/core/test_catalog.py

# Run with verbose output
pytest -v
```

### Test Organization

```
tests/
├── core/          # Core catalog and analysis
├── cli/           # Command-line interface
├── web/           # Web API and endpoints
├── shared/        # Shared utilities
├── jobs/          # Celery background jobs
└── conftest.py    # Pytest configuration
```

### Test Types

**Unit Tests** (fast, no external services):
```bash
pytest tests/core/ tests/shared/
```

**Integration Tests** (require PostgreSQL):
```bash
pytest -m integration
```

**All Tests**:
```bash
pytest
```

### Test Configuration

Tests are configured in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = [
    "-n", "4",              # 4 parallel workers
    "--tb=line",            # Short tracebacks
    "-m", "not e2e",        # Skip end-to-end tests
]
```

### Coverage

```bash
# Run with coverage
pytest --cov=lumina --cov-report=html

# View report
open htmlcov/index.html
```

**Current stats**: 642 tests passing, 8 skipped, 79% coverage

---

## Code Quality

### Pre-commit Hooks

Install pre-commit hooks:
```bash
pre-commit install
```

Hooks run automatically on commit:
- **Black** - Code formatting
- **isort** - Import sorting
- **flake8** - Linting
- **mypy** - Type checking

### Manual Quality Checks

```bash
# Format code
black lumina/ tests/

# Sort imports
isort lumina/ tests/

# Lint
flake8 lumina/ tests/

# Type check
mypy lumina/
```

### Pre-push Hook

**Known issue**: The pre-push hook sometimes hangs when running tests due to pytest-xdist parallel execution in git hook environment.

**Workaround**:
```bash
# Push without running hook
git push --no-verify

# Or run tests manually first
pytest
git push --no-verify
```

The tests themselves work fine - this is only an issue with the git hook subprocess environment.

---

## Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/your-feature-name
```

### 2. Make Changes

Edit code, add features, fix bugs.

### 3. Run Tests

```bash
# Run tests
pytest

# Run code quality
black lumina/ tests/
isort lumina/ tests/
flake8 lumina/ tests/
mypy lumina/
```

### 4. Commit

```bash
git add .
git commit -m "feat: your feature description"
```

Use conventional commit prefixes:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation
- `refactor:` - Code refactoring
- `test:` - Test changes
- `build:` - Build system changes

### 5. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Create pull request on GitHub.

---

## Project Structure

```
lumina/
├── lumina/                 # Main package
│   ├── api/               # FastAPI web routes
│   ├── cli/               # Command-line interface
│   ├── core/              # Core catalog and analysis
│   ├── db/                # Database models and connection
│   ├── jobs/              # Celery background jobs
│   ├── shared/            # Shared utilities
│   └── web/               # Web server
├── tests/                 # Test suite
├── docs/                  # Documentation
├── scripts/               # Operational scripts
├── Dockerfile             # Docker production image
├── docker-compose.yml     # Docker deployment
├── pyproject.toml         # Python package config
└── requirements.txt       # Dependencies
```

### Key Modules

**`lumina/core/catalog.py`**: Main catalog management
**`lumina/core/analyzer.py`**: Photo analysis pipeline
**`lumina/jobs/parallel_duplicates.py`**: Duplicate detection
**`lumina/cli/analyze.py`**: CLI entry point
**`lumina/web/main.py`**: Web server
**`lumina/db/connection.py`**: Database connection

---

## Debugging

### Enable Debug Logging

```bash
# Set in .env
LOG_LEVEL=DEBUG

# Or via environment
export LOG_LEVEL=DEBUG
lumina-analyze /catalog -s /photos
```

### Debug in IDE

**VS Code `launch.json`**:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Lumina Analyze",
      "type": "python",
      "request": "launch",
      "module": "lumina.cli.analyze",
      "args": ["/tmp/test-catalog", "-s", "/tmp/test-photos"],
      "console": "integratedTerminal"
    }
  ]
}
```

### Debug Tests

```bash
# Run single test with output
pytest -xvs tests/core/test_catalog.py::test_specific_function

# Drop into debugger on failure
pytest --pdb

# Debug in IDE (VS Code, PyCharm)
# Set breakpoint and run test through IDE's test runner
```

---

## Database Management

### Migrations

Schema is in `lumina/db/schema.sql`. For schema changes:

1. Update `schema.sql`
2. Create migration script in `scripts/migrations/`
3. Test migration on dev database
4. Document in migration script comments

### Reset Database

```bash
# Drop and recreate
dropdb lumina
createdb lumina

# Or clear catalog
lumina-analyze /catalog --clear
```

### Inspect Database

```bash
# Connect to database
psql lumina

# Useful queries
SELECT COUNT(*) FROM images;
SELECT COUNT(*) FROM duplicate_groups;
SELECT catalog_id, source_directory FROM catalogs;
```

---

## Performance Profiling

### Profile Analysis

```bash
# Profile with cProfile
python -m cProfile -o analyze.prof -m lumina.cli.analyze /catalog -s /photos

# View profile
python -m pstats analyze.prof
# Then in pstats: sort cumtime, stats 20
```

### GPU Profiling

```bash
# Monitor GPU usage
watch -n 1 nvidia-smi

# Detailed profiling
nvprof python -m lumina.cli.analyze /catalog -s /photos
```

---

## Contributing

### Before Submitting PR

- [ ] All tests pass (`pytest`)
- [ ] Code formatted (`black`, `isort`)
- [ ] No linting errors (`flake8`)
- [ ] Type checking passes (`mypy`)
- [ ] Documentation updated if needed
- [ ] Commit messages follow conventional format

### PR Guidelines

- Clear description of changes
- Link to related issue if applicable
- Screenshots for UI changes
- Test coverage for new features
- Update relevant documentation

See **[Contributing Guide](../guides/CONTRIBUTING.md)** for complete details.

---

## Useful Commands

```bash
# Run local dev server
scripts/dev/run_local.sh

# Clean Python cache
find . -type d -name __pycache__ -exec rm -r {} +
find . -type f -name "*.pyc" -delete

# Update dependencies
pip install --upgrade -e ".[dev]"

# Generate requirements.txt
pip freeze > requirements.txt

# Run single test file
pytest tests/core/test_catalog.py -v
```

---

## Getting Help

- **Documentation**: `/docs`
- **Issues**: https://github.com/irjudson/lumina/issues
- **Discussions**: https://github.com/irjudson/lumina/discussions
- **Architecture**: `docs/technical/ARCHITECTURE.md`
