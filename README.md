# Lumina

**Illuminate Your Memories**

Professional photo and video library manager with intelligent analysis, multi-layer duplicate detection, AI-powered classification, and event detection.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/tests-724%20passing-success.svg)](https://github.com/irjudson/lumina)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## Quick Start (5 Minutes)

### Prerequisites
- Docker & Docker Compose
- nvidia-docker2 (optional, for GPU acceleration)

### Run Lumina

```bash
# 1. Clone repository
git clone https://github.com/irjudson/lumina.git
cd lumina

# 2. Configure
cp .env.example .env
nano .env  # Set CATALOG_PATH and PHOTOS_PATH

# 3. Start Lumina
docker compose up -d

# 4. Open web UI
open http://localhost:8765
```

Lumina creates a default catalog on first start. Point it at your photo library and kick off a scan from the web UI.

**New to Lumina?** See the **[Quick Start Guide](docs/guides/QUICK_START.md)** for detailed setup instructions.

---

## Features

### Core Capabilities
- **High-Performance Scanning** — Multi-core parallel file discovery with EXIF/XMP metadata extraction
- **Five-Layer Duplicate Detection** — Exact match, re-import, format variant, preview-scale, and near-duplicate detection
- **Burst Management** — Auto-detect rapid-fire sequences and select the best shot
- **Event Detection** — Cluster GPS-tagged photos by time and location into photographic events
- **AI Image Classification** — Fast heuristic classification (screenshot, document, photo, etc.) with optional Ollama VLM refinement
- **Auto-Tagging** — GPU-accelerated OpenCLIP tag generation; Ollama VLM for descriptive tags
- **File Organization** — Date-based directory reorganization with confidence tiers and dry-run preview
- **Comprehensive Metadata** — EXIF, XMP, filename, and directory date sources with confidence scoring
- **RAW Support** — Native metadata extraction for CR2, CR3, NEF, ARW, DNG, and more

### Web Interface
- **Library view** — Infinite-scroll grid with filtering by status, content class, date, and tags
- **Tag browser** — Filter by any tag; primary tag shown on image hover
- **Duplicates** — Side-by-side comparison with accept/reject workflow and auto-resolve
- **Bursts** — Sequence review with best-shot selection
- **Events** — Browse photographic events by score; expand to see all images in a cluster
- **Map view** — Geographic display of GPS-tagged images using Leaflet
- **Timeline** — Chronological browsing
- **Collections** — Smart groupings
- **Settings** — Per-catalog configuration

### Advanced Features
- **GPU Acceleration** — 20-30x faster perceptual hashing with CUDA
- **Semantic Search** — CLIP embeddings stored in pgvector for similarity search
- **Real-Time Progress** — Server-sent events stream live job progress to the UI
- **Auto-Resolve Duplicates** — Quality-based automatic resolution (resolution → file size → filename heuristics)
- **Warehouse Scheduling** — Automated recurring job execution
- **Fully Tested** — 724 passing tests

---

## Architecture

**Single-container Docker deployment** with all services included:

```
┌──────────────────────────────────────────┐
│              Lumina Container            │
├──────────────────────────────────────────┤
│  PostgreSQL    FastAPI     Vue.js 3      │
│  (catalog)     (REST API)  (frontend)    │
│                                          │
│  Thread Pool   pgvector    GPU (opt.)    │
│  (jobs)        (embeddings) (CUDA)       │
└──────────────────────────────────────────┘
        │                  │
   [Catalog DB]      [Photo Library]
   (PostgreSQL)       (read-only)
```

- **PostgreSQL** — Catalog metadata, job tracking, ACID transactions
- **ThreadPoolExecutor** — Background job processing (scan, dedup, organize, classify, tag, etc.)
- **FastAPI** — REST API with SSE progress streaming
- **Vue.js 3** — Modern SPA with Pinia state management and Tailwind CSS
- **pgvector** — CLIP embedding storage for semantic similarity search
- **GPU** — Optional NVIDIA CUDA for perceptual hashing (20-30x speedup)

---

## Background Jobs

Jobs are submitted through the web UI or API and run in a background thread pool:

| Job | Description |
|-----|-------------|
| `scan` | Scan source directories, extract metadata |
| `extract_metadata_columns` | Populate typed DB columns from JSONB metadata |
| `hash_images_v2` | Compute perceptual hashes (dHash, aHash, wHash, dhash_16) |
| `detect_duplicates_v2` | Five-layer duplicate detection pipeline |
| `auto_resolve_duplicates` | Quality-based automatic duplicate resolution |
| `generate_thumbnails` | Generate image thumbnails |
| `detect_bursts` | Detect rapid-fire burst sequences |
| `detect_events` | Cluster GPS images into photographic events |
| `classify_images` | Heuristic + optional VLM content classification |
| `auto_tag` | AI-powered tag generation (OpenCLIP / Ollama) |
| `organize` | Reorganize files into date-based directory structure |

---

## Usage

### Web Interface (Recommended)

Access http://localhost:8765 to browse your library, review duplicates, manage tags, explore events on a map, and monitor job progress in real time.

### API

```bash
# List catalogs
GET /api/catalogs

# Start a scan job
POST /api/catalogs/{id}/jobs
{"job_type": "scan"}

# Get job status
GET /api/jobs/{job_id}

# List events
GET /api/catalogs/{id}/events
```

---

## Configuration

Edit `.env` to customize:

```bash
# Required
CATALOG_PATH=/path/to/catalog     # Where the catalog database is stored
PHOTOS_PATH=/path/to/photos       # Your photo library (mounted read-only)

# Optional performance tuning
WORKERS=32                         # CPU cores for processing
ENABLE_GPU=true                    # GPU acceleration

# Optional Ollama integration (for VLM classification and tagging)
OLLAMA_HOST=http://localhost:11434
```

**See [Configuration Guide](docs/deployment/CONFIGURATION.md) for all options.**

---

## GPU Acceleration

GPU support is built into the Docker image. Install nvidia-docker2, then `docker compose up`:

```bash
# Ubuntu/Debian
sudo apt-get install nvidia-docker2
sudo systemctl restart docker

# Verify
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

20-30x faster perceptual hashing; CLIP embeddings use GPU automatically when available.

**See [GPU Setup Guide](docs/guides/GPU_SETUP.md) for troubleshooting.**

---

## Supported Formats

- **Images:** JPEG, PNG, TIFF, BMP, GIF, WebP, HEIC/HEIF
- **RAW:** CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, SR2, RAF, and more
- **Videos:** MP4, MOV, AVI, MKV, M4V, WMV, WebM

---

## Documentation

- **[Quick Start](docs/guides/QUICK_START.md)** — Get running in 5 minutes
- **[User Guide](docs/guides/USER_GUIDE.md)** — Complete workflows and features
- **[Architecture](docs/technical/ARCHITECTURE.md)** — System design and components
- **[Docker Deployment](docs/deployment/DOCKER.md)** — Production setup
- **[Configuration](docs/deployment/CONFIGURATION.md)** — All environment variables
- **[Troubleshooting](docs/guides/TROUBLESHOOTING.md)** — Common issues and solutions
- **[Development](docs/technical/DEVELOPMENT.md)** — Contributing and local setup

---

## Development

```bash
git clone https://github.com/irjudson/lumina.git
cd lumina

python3.11 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run all tests
pytest

# Run only unit tests (no database required)
pytest -m "not integration"

# Code quality
black lumina/ tests/
isort lumina/ tests/
flake8 lumina/ tests/
mypy lumina/
```

**See [Development Guide](docs/technical/DEVELOPMENT.md) for complete instructions.**

---

## Supported Formats

- **Images:** JPEG, PNG, TIFF, BMP, GIF, WebP, HEIC/HEIF
- **RAW:** CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, SR2, RAF, and more
- **Videos:** MP4, MOV, AVI, MKV, M4V, WMV, WebM

---

## License

Apache License 2.0 — see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

Lumina builds on excellent open-source projects:

- [Pillow](https://python-pillow.org/) — Image processing
- [ExifTool](https://exiftool.org/) — Metadata extraction
- [FastAPI](https://fastapi.tiangolo.com/) — Web API
- [Vue.js](https://vuejs.org/) — Frontend
- [PostgreSQL](https://www.postgresql.org/) — Database
- [pgvector](https://github.com/pgvector/pgvector) — Vector similarity search
- [PyTorch](https://pytorch.org/) — GPU acceleration
- [open-clip-torch](https://github.com/mlfoundations/open_clip) — CLIP embeddings and tagging
- [Ollama](https://ollama.com/) — Local VLM inference
- [Leaflet](https://leafletjs.com/) — Map visualization
- [Click](https://click.palletsprojects.com/) — CLI framework
- [Rich](https://rich.readthedocs.io/) — Terminal output

---

## Author

**Ivan R. Judson** — [irjudson@gmail.com](mailto:irjudson@gmail.com)

---

## Project Links

- **Repository**: https://github.com/irjudson/lumina
- **Issues**: https://github.com/irjudson/lumina/issues
- **Discussions**: https://github.com/irjudson/lumina/discussions
- **Documentation**: [./docs](./docs)

---

*Developed using human-AI pair programming with Claude.*
