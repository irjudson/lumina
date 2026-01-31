# Repository Cleanup & Documentation Overhaul

**Date**: 2026-01-31
**Status**: Design Approved
**Goal**: Comprehensive cleanup for public release and long-term maintainability

## Context

The repository has evolved from multi-container to single-container architecture, from vam-tools to lumina naming, and accumulated debug/migration scripts. Current state is functional but messy, with outdated documentation that doesn't reflect Docker-first deployment model.

**Target deployment**: Docker-only for end users (single container with PostgreSQL, Redis, Celery, GPU support)

## Design Overview

Four-phase cleanup addressing root directory, documentation, README, and final polish.

---

## Phase 1: Root Directory Cleanup

### Delete Temporary Files

Remove all one-off debug/migration scripts (in git history if needed):
- `compute_hash_distances.py`
- `manual_finalizer.py`
- `migrate_duplicate_pairs.sql`
- `monitor_duplicate_job.sh`
- `monitor_migration.sh`
- `remove_burst_duplicates.sql`
- `run_duplicates_finalizer.py`
- `test_results.txt`
- `SESSION_STATE.md`
- `WARP.md`
- `Dockerfile.test`

### Scripts Directory Structure

**Keep and organize**:
```
scripts/
├── README.md          # Documentation for scripts directory
├── start.sh           # Container startup script (production)
├── dev/
│   └── run_local.sh   # Developer: run without Docker
└── migrations/
    └── migrate_geohash.py  # Historical migrations (if still relevant)
```

**Remove obsolete**:
- `scripts/kill_tests.sh` - pytest handles this
- `scripts/run_tests.sh` - use pytest directly
- `scripts/iphone-mount.sh` - user-specific, not project-related

### Root Directory Final State

Only essential files remain:
- `Dockerfile` - single-container production build
- `docker-compose.yml` - production deployment
- `pyproject.toml` - Python package configuration
- `requirements.txt` - dependencies
- `.env.example` - configuration template
- Standard configs (`.gitignore`, `.flake8`, `.pre-commit-config.yaml`)
- `LICENSE`, `README.md`

---

## Phase 2: Documentation Restructuring

### New Structure

```
docs/
├── guides/              # User-facing documentation
│   ├── QUICK_START.md   # NEW: 5-minute Docker setup
│   ├── USER_GUIDE.md    # UPDATE: Docker-first workflows
│   ├── GPU_SETUP.md     # UPDATE: GPU in single container
│   └── TROUBLESHOOTING.md  # UPDATE: Docker-specific issues
│
├── technical/           # Developer/architecture documentation
│   ├── ARCHITECTURE.md  # MAJOR UPDATE: Single-container design
│   ├── HOW_IT_WORKS.md  # UPDATE: Processing pipeline
│   ├── DEVELOPMENT.md   # NEW: Developer setup (native Python)
│   └── API.md           # NEW: Web API documentation
│
├── deployment/          # NEW: Production deployment guides
│   ├── DOCKER.md        # Docker production setup
│   └── CONFIGURATION.md # Environment variables, tuning
│
└── archive/             # Historical context
    └── (existing archives)
```

### Key Documentation Updates

#### NEW: `docs/guides/QUICK_START.md`
- 3-step Docker setup: clone, configure, run
- Single `docker compose up` command
- Access web UI at localhost:8765
- Example workflow with sample photos

#### UPDATE: `docs/guides/USER_GUIDE.md`
- Remove all `vam-*` command references
- Replace with Docker exec: `docker exec lumina lumina-analyze ...`
- Promote web UI as primary interface
- Update workflows for Docker environment

#### MAJOR UPDATE: `docs/technical/ARCHITECTURE.md`
Document current single-container architecture:
- PostgreSQL for catalog data + Celery results
- Redis for Celery broker
- All services in one container (no docker-compose networking)
- GPU sharing via NVIDIA MPS
- Background job processing with Celery
- FastAPI web server
- Vue.js frontend

#### UPDATE: `docs/guides/GPU_SETUP.md`
Simplify dramatically:
- GPU support is built into Docker image
- Users need: nvidia-docker2 installed, then `docker compose up`
- Remove multi-step PyTorch installation instructions (in Dockerfile)

#### NEW: `docs/technical/DEVELOPMENT.md`
Move native Python setup here (out of README):
- Local development without Docker
- Running tests
- Pre-commit hooks
- Code quality checks
- Contributing guidelines
- Document pre-push hook pytest issue and `--no-verify` workaround

#### NEW: `docs/deployment/DOCKER.md`
Production deployment guide:
- Volume configuration
- Environment variables
- GPU setup
- Backup strategies
- Monitoring

#### NEW: `docs/deployment/CONFIGURATION.md`
Complete environment variable reference:
- Required vs optional settings
- Performance tuning
- Security considerations

### Archive Obsolete Docs

Move to `docs/archive/`:
- `DOCKER_SETUP.md` - multi-container setup, no longer relevant
- `LOCAL_SETUP.md` - becomes `DEVELOPMENT.md`
- `POSTGRES_MIGRATION.md` - historical migration notes

### Update Test Documentation

- Correct test counts: 642 passed, 8 skipped (not 616)
- Document which tests are skipped and why
- Explain pytest-xdist parallel execution
- Note pre-push hook issue

---

## Phase 3: README Complete Rewrite

### New README Structure

**Docker-first approach** from line 1:

1. **Header** - Project name, tagline, badges (updated)
2. **Quick Start** - 5-minute Docker setup (prominent)
3. **Features** - Core capabilities and advanced features
4. **Architecture** - Single-container overview
5. **Usage** - Web UI (primary) + CLI (advanced)
6. **Configuration** - .env file basics
7. **Documentation** - Links to guides
8. **GPU Acceleration** - Built-in, just need nvidia-docker2
9. **Development** - Link to DEVELOPMENT.md
10. **License & Links**

### Key Changes

**Remove entirely**:
- All `vam-*` command references
- Native pip installation instructions (move to DEVELOPMENT.md)
- Multi-step Python setup
- ExifTool installation (in Docker image)

**Update**:
- Badges: Python 3.11+, Tests: 642 passing, add Docker badge
- Architecture: Single-container design
- Commands: `docker exec lumina lumina-analyze ...`
- Primary interface: Web UI at localhost:8765

**Emphasize**:
- Docker as only deployment method for users
- Web UI as primary interaction mode
- CLI via `docker exec` for advanced users
- GPU acceleration is built-in and automatic

---

## Phase 4: Final Cleanup & Configuration

### `.gitignore` Updates

Add/verify:
```gitignore
# Session/temporary files
SESSION_STATE.md
WARP.md
*.output

# Test artifacts
test_results.txt
.pytest_cache/
htmlcov/
.coverage

# Docker volumes
postgres_data/
lumina-pgdata/

# Development
.vscode/
.idea/
*.swp
*.swo

# Analysis artifacts
compute_*.py
manual_*.py
monitor_*.sh
```

### `pyproject.toml` Updates

Update metadata:
- version = "1.0.0"
- requires-python = ">=3.11"
- Update description
- Update repository URLs
- Fix any outdated dependencies

### `.env.example` Improvements

Comprehensive configuration template:
```bash
# Lumina Configuration
# Copy to .env and customize

# Required: Path Mapping
CATALOG_PATH=/path/to/catalog
PHOTOS_PATH=/path/to/photos

# Optional: Performance
WORKERS=32
CELERY_WORKERS=4

# Optional: GPU
ENABLE_GPU=true
CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
CUDA_MPS_LOG_DIRECTORY=/tmp/nvidia-log

# Optional: Database
POSTGRES_PASSWORD=change-me
POSTGRES_DB=lumina
POSTGRES_USER=lumina

# Optional: Web Interface
WEB_PORT=8765
WEB_HOST=0.0.0.0
```

### `docker-compose.yml` Cleanup

Add documentation:
- Comment explaining each environment variable
- Document volume mappings
- Explain GPU configuration
- Add healthcheck if missing

### Final Verification Checklist

- [ ] All vam-* references removed from entire repository
- [ ] All multi-container Docker files removed
- [ ] All test counts updated to 642
- [ ] All Python version references updated to 3.11+
- [ ] All documentation points to Docker as primary deployment
- [ ] No `__pycache__`, `.pyc`, or editor configs committed
- [ ] All temporary scripts deleted
- [ ] .gitignore covers all generated files

---

## Implementation Order

1. **Root directory cleanup** - Delete files, reorganize scripts
2. **Documentation restructuring** - Create new docs, update existing
3. **README rewrite** - Complete replacement
4. **Final polish** - Config files, .gitignore, verification

## Success Criteria

- Repository looks professional for public release
- New user can run Lumina in 5 minutes with Docker
- Documentation clearly reflects single-container architecture
- No references to obsolete vam-tools naming
- No temporary/debug files in root directory
- All test counts and metadata accurate
- Clear separation: Docker for users, native Python for developers

## Notes

- All deleted files remain in git history if needed
- Pre-push hook pytest hang is documented (use `--no-verify` workaround)
- GPU setup is dramatically simplified (built into image)
- Web UI promoted as primary interface over CLI
