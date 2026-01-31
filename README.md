# Lumina

**Illuminate Your Memories**

Professional photo and video library manager with GPU-accelerated analysis, intelligent duplicate detection, and burst sequence organization.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/tests-642%20passing-success.svg)](https://github.com/irjudson/lumina)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## ⚡ Quick Start (5 Minutes)

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

That's it! Lumina is now analyzing your photos.

**New to Lumina?** See the **[Quick Start Guide](docs/guides/QUICK_START.md)** for detailed setup instructions.

---

## Features

### Core Capabilities
- 🚀 **High-Performance Scanning** - Multi-core parallel processing
- 🎯 **Smart Duplicate Detection** - Perceptual hashing with quality scoring
- 📸 **Burst Management** - Auto-detect sequences, select best shot
- 🏷️ **Comprehensive Metadata** - EXIF, XMP, filename, and directory dates
- 📁 **RAW Support** - Native metadata extraction (no conversion needed)
- 🔄 **Date-Based Organization** - Reorganize into chronological structures
- 🖼️ **Modern Web UI** - Browse, compare, and manage your library

### Advanced Features
- ⚡ **GPU Acceleration** - 20-30x faster with CUDA (built into Docker image)
- 📊 **Real-Time Monitoring** - Live performance dashboard with GPU metrics
- 🔍 **FAISS Similarity Search** - GPU-accelerated for large catalogs
- 🛡️ **Corruption Detection** - Auto-flag corrupt or empty files
- ✅ **Fully Tested** - 642 passing tests, 79% coverage

---

## Architecture

**Single-container Docker deployment** with all services included:
- **PostgreSQL** - Catalog data and Celery results
- **Redis** - Celery task broker
- **Celery** - Background job processing
- **FastAPI** - Web API server
- **Vue.js** - Frontend UI
- **GPU Support** - NVIDIA MPS for multi-process sharing

All services run together in one container for maximum simplicity.

---

## Usage

### Web Interface (Recommended)

Access http://localhost:8765 to:
- Browse your entire photo library with metadata
- Review duplicate groups with side-by-side comparison
- Monitor real-time analysis progress
- View statistics and storage insights

### Command Line (Advanced)

Run commands inside the container:

```bash
# Trigger manual analysis
docker exec lumina lumina-analyze /catalog -s /photos --detect-duplicates

# Force complete re-scan
docker exec lumina lumina-analyze /catalog -s /photos --clear

# Organize into date-based structure
docker exec lumina lumina-organize /catalog \
  --output-dir /photos-organized \
  --format "{year}/{month}"
```

---

## Configuration

Edit `.env` file to customize:

```bash
# Required - Where to store catalog database
CATALOG_PATH=/path/to/catalog

# Required - Your photo library location
PHOTOS_PATH=/path/to/photos

# Optional - Performance tuning
WORKERS=32                  # CPU cores for processing
CELERY_WORKERS=4            # Background job workers
ENABLE_GPU=true             # GPU acceleration
```

**See [Configuration Guide](docs/deployment/CONFIGURATION.md) for all options.**

---

## GPU Acceleration

GPU support is **built into the Docker image** - no manual setup needed!

Just install nvidia-docker2:

```bash
# Ubuntu/Debian
sudo apt-get install nvidia-docker2
sudo systemctl restart docker

# Verify GPU access
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

Then `docker compose up` - GPU acceleration is automatic (20-30x faster).

**See [GPU Setup Guide](docs/guides/GPU_SETUP.md) for troubleshooting.**

---

## Documentation

📖 **[Quick Start](docs/guides/QUICK_START.md)** - Get running in 5 minutes
📚 **[User Guide](docs/guides/USER_GUIDE.md)** - Complete workflows and features
🏗️ **[Architecture](docs/technical/ARCHITECTURE.md)** - System design and components
🐳 **[Docker Deployment](docs/deployment/DOCKER.md)** - Production setup
⚙️ **[Configuration](docs/deployment/CONFIGURATION.md)** - All environment variables
🔧 **[Troubleshooting](docs/guides/TROUBLESHOOTING.md)** - Common issues and solutions
👨‍💻 **[Development](docs/technical/DEVELOPMENT.md)** - Contributing and local setup

---

## Supported Formats

- **Images:** JPEG, PNG, TIFF, BMP, GIF, WEBP, HEIC/HEIF
- **RAW Formats:** CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, SR2, RAF, and more
- **Videos:** MP4, MOV, AVI, MKV, and more

---

## Management

### View Logs
```bash
docker compose logs -f
```

### Restart Lumina
```bash
docker compose restart
```

### Stop Lumina
```bash
docker compose down
```

### Update Lumina
```bash
git pull origin main
docker compose build
docker compose up -d
```

---

## Development

For developers who want to contribute or run Lumina natively:

```bash
# Clone repository
git clone https://github.com/irjudson/lumina.git
cd lumina

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install with development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run code quality checks
black lumina/ tests/
isort lumina/ tests/
flake8 lumina/ tests/
mypy lumina/
```

**See [Development Guide](docs/technical/DEVELOPMENT.md) for complete instructions.**

---

## Contributing

We welcome contributions! Please see our **[Contributing Guide](docs/guides/CONTRIBUTING.md)** for:

- Setting up your development environment
- Running tests
- Code style and quality standards
- Submitting pull requests

### Quick Contribution Checklist

- [ ] All tests pass (`pytest`)
- [ ] Code formatted (`black`, `isort`)
- [ ] No linting errors (`flake8`)
- [ ] Type checking passes (`mypy`)
- [ ] Documentation updated
- [ ] Conventional commit messages

---

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

Lumina builds on excellent open-source projects:

- [Pillow](https://python-pillow.org/) - Image processing
- [ExifTool](https://exiftool.org/) - Metadata extraction
- [Click](https://click.palletsprojects.com/) - CLI framework
- [Rich](https://rich.readthedocs.io/) - Terminal output
- [FastAPI](https://fastapi.tiangolo.com/) - Web API
- [Pydantic](https://docs.pydantic.dev/) - Data validation
- [PyTorch](https://pytorch.org/) - GPU acceleration
- [FAISS](https://github.com/facebookresearch/faiss) - Similarity search
- [Vue.js](https://vuejs.org/) - Frontend
- [PostgreSQL](https://www.postgresql.org/) - Database
- [Redis](https://redis.io/) - Message broker
- [Celery](https://docs.celeryproject.org/) - Task queue

---

## Author

**Ivan R. Judson** - [irjudson@gmail.com](mailto:irjudson@gmail.com)

---

## Project Links

- 🏠 **Repository**: https://github.com/irjudson/lumina
- 🐛 **Issues**: https://github.com/irjudson/lumina/issues
- 💬 **Discussions**: https://github.com/irjudson/lumina/discussions
- 📖 **Documentation**: [./docs](./docs)

---

## Development Story

This project was developed using human-AI pair programming with Claude. The collaboration followed established engineering principles to ensure code quality without requiring exhaustive human review.

**Result**: Production-ready tool with continuous improvements, **642 passing tests** and **79% coverage**.

Read more about the **[Development Approach](docs/technical/DEVELOPMENT_APPROACH.md)**.
