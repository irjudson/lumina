# Docker Deployment Guide

Production deployment guide for Lumina using Docker.

## Overview

Lumina runs as a **single-container** Docker deployment with all services included:
- PostgreSQL database
- Redis broker
- Celery workers
- FastAPI web server
- Vue.js frontend

GPU support is built-in and automatically enabled when nvidia-docker2 is available.

---

## Quick Deployment

### 1. Install Docker

**Ubuntu/Debian**:
```bash
sudo apt-get update
sudo apt-get install docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# Log out and back in
```

**Other platforms**: See [Docker documentation](https://docs.docker.com/get-docker/)

### 2. Optional: GPU Support

For GPU-accelerated processing (20-30x faster):

```bash
# Install nvidia-docker2
sudo apt-get install nvidia-docker2
sudo systemctl restart docker

# Verify
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

### 3. Deploy Lumina

```bash
# Clone repository
git clone https://github.com/irjudson/lumina.git
cd lumina

# Configure
cp .env.example .env
nano .env  # Set CATALOG_PATH and PHOTOS_PATH

# Start
docker compose up -d

# View logs
docker compose logs -f
```

Access web UI at http://localhost:8765

---

## Configuration

### Environment Variables

Edit `.env` file before starting:

**Required**:
```bash
CATALOG_PATH=/path/to/catalog    # Database storage location
PHOTOS_PATH=/path/to/photos      # Photo library location
```

**Performance**:
```bash
WORKERS=32                       # CPU cores for analysis
CELERY_WORKERS=4                 # Background job workers
ENABLE_GPU=true                  # GPU acceleration
```

**Database**:
```bash
POSTGRES_PASSWORD=change-me      # Database password
POSTGRES_DB=lumina
POSTGRES_USER=lumina
```

**Web Server**:
```bash
WEB_PORT=8765                    # External port
WEB_HOST=0.0.0.0                 # Allow external access
```

See **[Configuration Guide](./CONFIGURATION.md)** for complete reference.

### Volume Mapping

The `docker-compose.yml` maps these volumes:

```yaml
volumes:
  - ${CATALOG_PATH}:/catalog      # Catalog database
  - ${PHOTOS_PATH}:/photos:ro     # Photo library (read-only)
  - postgres_data:/var/lib/postgresql/data  # PostgreSQL data
```

**Important**: Use absolute paths in `.env`

---

## Production Setup

### Recommended Configuration

```bash
# .env for production
CATALOG_PATH=/mnt/storage/lumina-catalog
PHOTOS_PATH=/mnt/storage/photos

# Security
POSTGRES_PASSWORD=<strong-random-password>

# Performance
WORKERS=32                       # All CPU cores
CELERY_WORKERS=8                 # 2-4x number of CPU cores
ENABLE_GPU=true                  # If GPU available

# Web server
WEB_PORT=8765
WEB_HOST=0.0.0.0                 # Allow network access
```

### Storage Considerations

**Catalog database** (CATALOG_PATH):
- Size: ~0.5-1GB per 100k images
- Performance: Fast local SSD recommended
- Backup: Critical - contains all metadata and analysis

**Photo library** (PHOTOS_PATH):
- Size: Original photo library size
- Performance: Can be network storage (NAS)
- Access: Read-only mounted in container

### Resource Requirements

**Minimum**:
- 4 CPU cores
- 8GB RAM
- 10GB disk for catalog (per 1M images)

**Recommended**:
- 16+ CPU cores
- 32GB+ RAM
- SSD for catalog database
- NVIDIA GPU with 8GB+ VRAM

**Large Libraries** (1M+ images):
- 32+ CPU cores
- 64GB+ RAM
- NVMe SSD for catalog
- NVIDIA GPU with 24GB+ VRAM

---

## Management

### Start/Stop

```bash
# Start in background
docker compose up -d

# Stop
docker compose down

# Restart
docker compose restart

# Stop and remove volumes (DELETES DATA)
docker compose down -v
```

### View Logs

```bash
# All logs
docker compose logs

# Follow logs (live)
docker compose logs -f

# Specific service
docker compose logs -f lumina

# Last 100 lines
docker compose logs --tail=100
```

### Execute Commands

```bash
# Run analysis manually
docker exec lumina lumina-analyze /catalog -s /photos

# Access shell
docker exec -it lumina bash

# Check PostgreSQL
docker exec lumina psql -U lumina -d lumina -c "SELECT COUNT(*) FROM images;"

# Check Redis
docker exec lumina redis-cli ping
```

### Update Lumina

```bash
# Pull latest changes
git pull origin main

# Rebuild image
docker compose build

# Restart with new image
docker compose down
docker compose up -d
```

---

## Monitoring

### Health Checks

**Automated Health Monitoring**:

The container includes a built-in healthcheck that monitors:
- **PostgreSQL**: Database accepting connections
- **Redis**: Message broker responsive
- **Web API**: FastAPI serving requests

```bash
# View health status
docker ps --format "table {{.Names}}\t{{.Status}}"

# Detailed health information
docker inspect lumina --format='{{json .State.Health}}' | python3 -m json.tool

# Health status values:
#   starting - During 60-second startup period
#   healthy  - All checks passing
#   unhealthy - One or more checks failing
```

**Container Orchestration Integration**:

The healthcheck is exposed through Docker's health API for:
- **Docker Swarm**: Service availability and routing decisions
- **Kubernetes**: Liveness and readiness probes (via Docker runtime)
- **Load Balancers**: Health-based traffic routing
- **Monitoring Systems**: Automated alerting on unhealthy status

**Manual Health Checks**:

```bash
# Container status
docker compose ps

# Resource usage
docker stats lumina

# GPU usage (if enabled)
docker exec lumina nvidia-smi
```

### Web Dashboard

Access real-time monitoring at http://localhost:8765:
- Analysis progress
- CPU/GPU utilization
- Throughput metrics
- Job queue status

### Log Monitoring

```bash
# Watch for errors
docker compose logs -f | grep -i error

# Monitor analysis progress
docker compose logs -f | grep "Processing"

# Check Celery workers
docker compose logs -f | grep "celery"
```

---

## Backup & Recovery

### Backup Catalog

**Recommended: Automated backups**

```bash
# Create backup script
cat > backup-lumina.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/mnt/backups/lumina"

# Backup PostgreSQL database
docker exec lumina pg_dump -U lumina lumina | gzip > "$BACKUP_DIR/lumina_$DATE.sql.gz"

# Backup catalog directory (includes job progress)
tar -czf "$BACKUP_DIR/catalog_$DATE.tar.gz" -C /path/to/catalog .

# Keep last 30 days
find "$BACKUP_DIR" -name "lumina_*.sql.gz" -mtime +30 -delete
find "$BACKUP_DIR" -name "catalog_*.tar.gz" -mtime +30 -delete
EOF

chmod +x backup-lumina.sh

# Run daily via cron
# 0 2 * * * /path/to/backup-lumina.sh
```

### Restore from Backup

```bash
# Stop Lumina
docker compose down

# Restore PostgreSQL
gunzip < lumina_20260131.sql.gz | docker exec -i lumina psql -U lumina lumina

# Restore catalog directory
cd /path/to/catalog
tar -xzf /mnt/backups/lumina/catalog_20260131.tar.gz

# Start Lumina
docker compose up -d
```

---

## Troubleshooting

### Container Won't Start

**Check logs**:
```bash
docker compose logs lumina
```

**Common issues**:
- Invalid CATALOG_PATH or PHOTOS_PATH in `.env`
- Port 8765 already in use
- Permissions on volume directories
- Out of disk space

**Solutions**:
```bash
# Check paths exist
ls -la $CATALOG_PATH
ls -la $PHOTOS_PATH

# Check port availability
sudo netstat -tlnp | grep 8765

# Check disk space
df -h
```

### Performance Issues

**Symptoms**: Slow analysis, high CPU usage, low throughput

**Solutions**:
```bash
# Increase workers in .env
WORKERS=32
CELERY_WORKERS=8

# Enable GPU
ENABLE_GPU=true

# Move catalog to faster storage
# Edit CATALOG_PATH in .env to SSD location
```

### GPU Not Detected

**Check GPU access**:
```bash
docker exec lumina nvidia-smi
```

**If fails**:
1. Verify nvidia-docker2 installed
2. Check ENABLE_GPU=true in `.env`
3. Restart Docker: `sudo systemctl restart docker`
4. Rebuild container: `docker compose build && docker compose up -d`

### Database Connection Errors

**Check PostgreSQL**:
```bash
# Test connection
docker exec lumina psql -U lumina -d lumina -c "SELECT 1;"

# Check logs
docker compose logs | grep postgres
```

**Reset database** (DELETES DATA):
```bash
docker compose down -v
docker compose up -d
```

---

## Security

### Network Exposure

By default, Lumina binds to `0.0.0.0:8765` (accessible from network).

**Restrict to localhost only**:
```bash
# In .env
WEB_HOST=127.0.0.1
```

**Use reverse proxy** (recommended for production):
```nginx
# nginx configuration
server {
    listen 80;
    server_name photos.example.com;

    location / {
        proxy_pass http://localhost:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Database Security

```bash
# Change default password in .env
POSTGRES_PASSWORD=<strong-random-password>

# Rebuild to apply
docker compose down
docker compose up -d
```

### File Permissions

Photos are mounted read-only by default:
```yaml
- ${PHOTOS_PATH}:/photos:ro
```

This prevents accidental modification of your photo library.

---

## Advanced Configuration

### Custom Docker Compose

Create `docker-compose.override.yml` for customizations:

```yaml
services:
  lumina:
    ports:
      - "9000:8765"  # Custom external port
    environment:
      - CUSTOM_VAR=value
```

### Resource Limits

Limit container resources:

```yaml
services:
  lumina:
    deploy:
      resources:
        limits:
          cpus: '16'
          memory: 32G
        reservations:
          cpus: '8'
          memory: 16G
```

---

## Support

- **Troubleshooting**: See [TROUBLESHOOTING.md](../guides/TROUBLESHOOTING.md)
- **Configuration**: See [CONFIGURATION.md](./CONFIGURATION.md)
- **Issues**: https://github.com/irjudson/lumina/issues
- **Discussions**: https://github.com/irjudson/lumina/discussions
