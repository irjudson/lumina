# Configuration Reference

Complete reference for all Lumina configuration options.

## Configuration File

Lumina is configured via environment variables in the `.env` file.

```bash
# Create from template
cp .env.example .env

# Edit configuration
nano .env
```

---

## Required Configuration

### Paths

**`CATALOG_PATH`** (required)
- **Description**: Where Lumina stores its catalog database
- **Type**: Absolute file path
- **Example**: `/mnt/storage/lumina-catalog`
- **Notes**:
  - Must be writable by container
  - Recommend fast local SSD
  - Size: ~0.5-1GB per 100k images

**`PHOTOS_PATH`** (required)
- **Description**: Your photo library location
- **Type**: Absolute file path
- **Example**: `/mnt/storage/photos`
- **Notes**:
  - Can be network storage (NAS)
  - Mounted read-only in container
  - All subdirectories will be scanned

---

## Performance Configuration

### CPU Workers

**`WORKERS`**
- **Description**: Number of CPU cores for parallel processing
- **Type**: Integer
- **Default**: Auto-detect (all cores)
- **Example**: `WORKERS=32`
- **Recommendations**:
  - Small libraries (<10k images): 4-8
  - Medium libraries (10k-100k): 16-32
  - Large libraries (>100k): 32-64
- **Notes**: Higher isn't always better - balance with RAM

**`CELERY_WORKERS`**
- **Description**: Number of Celery background workers
- **Type**: Integer
- **Default**: 4
- **Example**: `CELERY_WORKERS=8`
- **Recommendations**:
  - Light usage: 2-4
  - Medium usage: 4-8
  - Heavy usage: 8-16
- **Notes**: Each worker uses ~2GB RAM

### GPU Configuration

**`ENABLE_GPU`**
- **Description**: Enable GPU acceleration
- **Type**: Boolean (true/false)
- **Default**: `true`
- **Example**: `ENABLE_GPU=true`
- **Requirements**: nvidia-docker2 installed
- **Impact**: 20-30x faster perceptual hashing

**`CUDA_MPS_PIPE_DIRECTORY`**
- **Description**: NVIDIA MPS pipe directory for multi-process GPU sharing
- **Type**: File path
- **Default**: `/tmp/nvidia-mps`
- **Example**: `CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps`
- **Notes**: Only relevant if using GPU

**`CUDA_MPS_LOG_DIRECTORY`**
- **Description**: NVIDIA MPS log directory
- **Type**: File path
- **Default**: `/tmp/nvidia-log`
- **Example**: `CUDA_MPS_LOG_DIRECTORY=/tmp/nvidia-log`

---

## Database Configuration

### PostgreSQL

**`POSTGRES_HOST`**
- **Description**: PostgreSQL server hostname
- **Type**: Hostname or IP
- **Default**: `localhost` (internal)
- **Example**: `POSTGRES_HOST=localhost`
- **Notes**: Keep as localhost for Docker deployment

**`POSTGRES_PORT`**
- **Description**: PostgreSQL server port
- **Type**: Integer
- **Default**: `5432`
- **Example**: `POSTGRES_PORT=5432`

**`POSTGRES_DB`**
- **Description**: Database name
- **Type**: String
- **Default**: `lumina`
- **Example**: `POSTGRES_DB=lumina`

**`POSTGRES_USER`**
- **Description**: Database username
- **Type**: String
- **Default**: `lumina`
- **Example**: `POSTGRES_USER=lumina`

**`POSTGRES_PASSWORD`**
- **Description**: Database password
- **Type**: String
- **Default**: `buffalo-jump`
- **Example**: `POSTGRES_PASSWORD=secure-random-password`
- **Security**: Change for production!

### Redis

**`REDIS_HOST`**
- **Description**: Redis server hostname
- **Type**: Hostname or IP
- **Default**: `localhost` (internal)
- **Example**: `REDIS_HOST=localhost`

**`REDIS_PORT`**
- **Description**: Redis server port
- **Type**: Integer
- **Default**: `6379`
- **Example**: `REDIS_PORT=6379`

**`CELERY_BROKER_URL`**
- **Description**: Celery message broker URL
- **Type**: URL string
- **Default**: `redis://localhost:6379/0`
- **Example**: `CELERY_BROKER_URL=redis://localhost:6379/0`
- **Notes**: Must be Redis (PostgreSQL not supported as broker)

**`CELERY_RESULT_BACKEND`**
- **Description**: Celery result backend URL
- **Type**: URL string
- **Default**: `db+postgresql://lumina:password@localhost:5432/lumina`
- **Example**: See default
- **Notes**: Uses PostgreSQL for persistence

---

## Web Server Configuration

**`WEB_PORT`**
- **Description**: External port for web interface
- **Type**: Integer
- **Default**: `8765`
- **Example**: `WEB_PORT=8080`
- **Notes**: Access UI at http://localhost:WEB_PORT

**`WEB_HOST`**
- **Description**: Host binding for web server
- **Type**: IP address
- **Default**: `0.0.0.0` (all interfaces)
- **Example**: `WEB_HOST=127.0.0.1` (localhost only)
- **Security**: Use `127.0.0.1` if only local access needed

---

## Analysis Configuration

### Duplicate Detection

**`SIMILARITY_THRESHOLD`**
- **Description**: Hamming distance threshold for duplicate detection
- **Type**: Integer (0-64)
- **Default**: `5`
- **Example**: `SIMILARITY_THRESHOLD=3`
- **Guidelines**:
  - 0-3: Very strict (identical images only)
  - 4-6: Recommended (similar images)
  - 7-10: Loose (more false positives)
- **Notes**: Lower = stricter matching

**`AUTO_SELECT_BEST`**
- **Description**: Automatically select best quality duplicate
- **Type**: Boolean
- **Default**: `true`
- **Example**: `AUTO_SELECT_BEST=false`
- **Notes**: Uses quality scoring to pick best image

### Date Extraction

**`DATE_CONFIDENCE_THRESHOLD`**
- **Description**: Minimum confidence level for date extraction
- **Type**: Float (0.0-1.0)
- **Default**: `0.5`
- **Example**: `DATE_CONFIDENCE_THRESHOLD=0.7`
- **Levels**:
  - 1.0: High confidence (EXIF DateTimeOriginal)
  - 0.8: Medium-high (EXIF CreateDate)
  - 0.5: Medium (XMP date tags)
  - 0.3: Low (filename patterns)
  - 0.1: Very low (directory structure)

---

## Logging Configuration

**`LOG_LEVEL`**
- **Description**: Logging verbosity
- **Type**: String
- **Default**: `INFO`
- **Options**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- **Example**: `LOG_LEVEL=DEBUG`
- **Notes**: Use DEBUG for troubleshooting

**`LOG_FORMAT`**
- **Description**: Log message format
- **Type**: String
- **Default**: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- **Example**: Custom format string

---

## Advanced Configuration

### Performance Tuning

**`BATCH_SIZE`**
- **Description**: Number of images processed per batch
- **Type**: Integer
- **Default**: `100`
- **Example**: `BATCH_SIZE=500`
- **Recommendations**:
  - Low RAM: 50-100
  - Medium RAM: 100-200
  - High RAM: 200-500

**`CACHE_SIZE`**
- **Description**: Metadata cache size (MB)
- **Type**: Integer
- **Default**: `1024` (1GB)
- **Example**: `CACHE_SIZE=2048`
- **Notes**: Larger cache improves performance for re-scans

**`THUMBNAIL_CACHE_SIZE`**
- **Description**: Maximum thumbnail cache size (MB)
- **Type**: Integer
- **Default**: `5000` (5GB)
- **Example**: `THUMBNAIL_CACHE_SIZE=10000`

### Network Optimization

**`NETWORK_TIMEOUT`**
- **Description**: Timeout for network filesystem operations (seconds)
- **Type**: Integer
- **Default**: `30`
- **Example**: `NETWORK_TIMEOUT=60`
- **Notes**: Increase for slow NAS

**`MAX_RETRIES`**
- **Description**: Maximum retries for failed operations
- **Type**: Integer
- **Default**: `3`
- **Example**: `MAX_RETRIES=5`

---

## Environment-Specific Examples

### Development

```bash
# .env for development
CATALOG_PATH=/home/user/dev/lumina-catalog
PHOTOS_PATH=/home/user/Pictures

WORKERS=4
CELERY_WORKERS=2
ENABLE_GPU=false

LOG_LEVEL=DEBUG
WEB_HOST=127.0.0.1
WEB_PORT=8765
```

### Production (Small Library)

```bash
# .env for small library (<50k images)
CATALOG_PATH=/mnt/ssd/lumina-catalog
PHOTOS_PATH=/mnt/storage/photos

WORKERS=16
CELERY_WORKERS=4
ENABLE_GPU=true

POSTGRES_PASSWORD=<strong-random>
LOG_LEVEL=INFO
WEB_HOST=0.0.0.0
WEB_PORT=8765
```

### Production (Large Library)

```bash
# .env for large library (>500k images)
CATALOG_PATH=/mnt/nvme/lumina-catalog
PHOTOS_PATH=/mnt/nas/photos

WORKERS=64
CELERY_WORKERS=16
ENABLE_GPU=true

BATCH_SIZE=500
CACHE_SIZE=4096
THUMBNAIL_CACHE_SIZE=20000

POSTGRES_PASSWORD=<strong-random>
LOG_LEVEL=WARNING
WEB_HOST=0.0.0.0
WEB_PORT=8765

NETWORK_TIMEOUT=60
MAX_RETRIES=5
```

---

## Validation

### Check Configuration

```bash
# Verify paths exist
ls -la $CATALOG_PATH
ls -la $PHOTOS_PATH

# Test database connection
docker exec lumina psql -U lumina -d lumina -c "SELECT 1;"

# Test Redis
docker exec lumina redis-cli ping

# Check GPU (if enabled)
docker exec lumina nvidia-smi
```

### Common Mistakes

**Invalid paths**:
```bash
# Wrong - relative path
CATALOG_PATH=./catalog

# Right - absolute path
CATALOG_PATH=/home/user/lumina-catalog
```

**Missing password change**:
```bash
# Wrong - default password
POSTGRES_PASSWORD=buffalo-jump

# Right - strong password
POSTGRES_PASSWORD=<random-secure-password>
```

**Port conflicts**:
```bash
# Check if port in use
sudo netstat -tlnp | grep 8765

# Use different port if needed
WEB_PORT=8080
```

---

## Security Best Practices

1. **Change default passwords**:
   ```bash
   POSTGRES_PASSWORD=$(openssl rand -base64 32)
   ```

2. **Restrict network access**:
   ```bash
   WEB_HOST=127.0.0.1  # Localhost only
   ```

3. **Use strong passwords**:
   - Minimum 20 characters
   - Random alphanumeric + symbols
   - Don't commit `.env` to git

4. **Regular backups**:
   - Backup catalog database daily
   - Keep multiple backup generations
   - Test restore procedures

5. **File permissions**:
   ```bash
   chmod 600 .env  # Only owner can read
   ```

---

## Troubleshooting Configuration

### Container won't start

**Check syntax**:
```bash
# Verify .env syntax (no spaces around =)
cat .env

# Common error:
WORKERS = 32  # Wrong
WORKERS=32    # Right
```

### Performance issues

**Check resource usage**:
```bash
# Container stats
docker stats lumina

# Adjust based on available resources
WORKERS=16      # Reduce if CPU maxed
CELERY_WORKERS=4  # Reduce if RAM maxed
```

### Database errors

**Check connection string**:
```bash
# Ensure format is correct
CELERY_RESULT_BACKEND=db+postgresql://USER:PASS@HOST:PORT/DB
```

---

## Support

- **Examples**: See `.env.example`
- **Docker Guide**: [DOCKER.md](./DOCKER.md)
- **Troubleshooting**: [../guides/TROUBLESHOOTING.md](../guides/TROUBLESHOOTING.md)
- **Issues**: https://github.com/irjudson/lumina/issues
