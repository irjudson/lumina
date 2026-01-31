# Quick Start Guide

Get Lumina running in 5 minutes with Docker.

## Prerequisites

- **Docker** and **Docker Compose** installed
- **nvidia-docker2** (optional, for GPU acceleration)
- **8GB+ RAM** recommended
- **Storage**: Space for your photo catalog database

### Install Docker

**Ubuntu/Debian**:
```bash
sudo apt-get update
sudo apt-get install docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# Log out and back in for group changes
```

**macOS**:
Install [Docker Desktop](https://www.docker.com/products/docker-desktop)

**Windows**:
Install [Docker Desktop](https://www.docker.com/products/docker-desktop) with WSL2 backend

### Optional: GPU Acceleration

For 20-30x faster processing, install nvidia-docker2:

```bash
# Ubuntu/Debian
sudo apt-get install nvidia-docker2
sudo systemctl restart docker

# Verify GPU access
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/irjudson/lumina.git
cd lumina
```

### 2. Configure Environment

```bash
# Copy example configuration
cp .env.example .env

# Edit configuration (use your favorite editor)
nano .env
```

**Required settings** in `.env`:
```bash
# Where Lumina stores its database
CATALOG_PATH=/path/to/catalog

# Your photo library location
PHOTOS_PATH=/path/to/photos
```

**Example**:
```bash
CATALOG_PATH=/home/username/lumina-catalog
PHOTOS_PATH=/home/username/Pictures
```

### 3. Start Lumina

```bash
docker compose up -d
```

That's it! Lumina is now running and analyzing your photos in the background.

---

## Access Lumina

### Web Interface

Open your browser to:
```
http://localhost:8765
```

You'll see:
- **Dashboard**: Analysis progress, statistics
- **Browse**: Your photo library with metadata
- **Duplicates**: Side-by-side duplicate comparison
- **Performance**: Real-time GPU and CPU metrics

### Check Status

```bash
# View logs
docker compose logs -f

# Check container status
docker compose ps

# Stop Lumina
docker compose down
```

---

## First Time Usage

When you first start Lumina, it will:

1. **Initialize database** - Create PostgreSQL tables (30 seconds)
2. **Scan photo library** - Discover all photos/videos
3. **Extract metadata** - Read EXIF, XMP, dates
4. **Detect duplicates** - Find similar images (if enabled)
5. **Calculate quality** - Score images for duplicate resolution

**Progress tracking**: Watch real-time progress at http://localhost:8765

**Performance**:
- **CPU**: 32-core system processes ~5,000 images/minute
- **GPU**: 20-30x faster perceptual hashing
- **Network storage**: Incremental discovery prevents blocking

---

## Example Workflow

### 1. Initial Analysis

```bash
# Start Lumina (automatic analysis begins)
docker compose up -d

# Watch progress
docker compose logs -f lumina
```

### 2. Browse Your Library

Open http://localhost:8765 and:
- View all photos with extracted metadata
- See date extraction confidence levels
- Check storage statistics
- Review analysis performance metrics

### 3. Review Duplicates

Navigate to **"View Duplicates"** to:
- See groups of similar images
- Compare side-by-side
- Review quality scores
- See recommended deletions

### 4. Organize Library (Optional)

Reorganize into date-based structure:

```bash
docker exec lumina lumina-organize /catalog \
  --output-dir /photos-organized \
  --format "{year}/{month}"
```

---

## Common Tasks

### Re-scan Photos

Add new photos and re-scan:

```bash
# Restart container (automatic incremental scan)
docker compose restart lumina

# Or trigger manually
docker exec lumina lumina-analyze /catalog -s /photos
```

### Adjust Workers

Edit `.env` to change CPU usage:

```bash
WORKERS=16  # Use 16 CPU cores instead of all
```

Then restart:
```bash
docker compose down
docker compose up -d
```

### Enable GPU

Edit `.env`:
```bash
ENABLE_GPU=true
```

Restart:
```bash
docker compose down
docker compose up -d
```

---

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs lumina

# Common issues:
# - Invalid CATALOG_PATH or PHOTOS_PATH in .env
# - Port 8765 already in use
# - Docker not running
```

### No GPU detected

```bash
# Verify nvidia-docker2
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi

# If that works but Lumina doesn't use GPU:
# - Check ENABLE_GPU=true in .env
# - Restart container
```

### Slow performance

```bash
# Increase workers in .env
WORKERS=32

# Enable GPU
ENABLE_GPU=true

# Check if database is on slow storage
# Move CATALOG_PATH to fast local disk
```

See **[Troubleshooting Guide](./TROUBLESHOOTING.md)** for complete solutions.

---

## Next Steps

- **[User Guide](./USER_GUIDE.md)** - Complete workflows and advanced features
- **[Configuration](../deployment/CONFIGURATION.md)** - All environment variables
- **[GPU Setup](./GPU_SETUP.md)** - Detailed GPU configuration
- **[Architecture](../technical/ARCHITECTURE.md)** - How Lumina works

---

## Getting Help

- **Issues**: https://github.com/irjudson/lumina/issues
- **Discussions**: https://github.com/irjudson/lumina/discussions
- **Documentation**: https://github.com/irjudson/lumina/tree/main/docs
