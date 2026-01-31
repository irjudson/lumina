# Lumina Architecture

Modern photo library management system with GPU-accelerated analysis and intelligent duplicate detection.

## Overview

Lumina is designed for managing large photo libraries (100k+ images) with:
- **Zero data loss** - All operations are safe and reversible
- **High performance** - Multi-core CPU + optional GPU acceleration
- **Intelligent analysis** - Metadata extraction, duplicate detection, quality scoring
- **Simple deployment** - Single Docker container with all services included

---

## Deployment Architecture

### Single-Container Design

All services run in one Docker container for maximum simplicity:

```
┌─────────────────────────────────────────────────────────┐
│                   Lumina Container                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  PostgreSQL  │  │    Redis     │  │   Celery     │ │
│  │   Database   │  │    Broker    │  │   Workers    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   FastAPI    │  │   Vue.js     │  │     GPU      │ │
│  │   Web API    │  │   Frontend   │  │  (optional)  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                         │
└─────────────────────────────────────────────────────────┘
           │                    │
           ↓                    ↓
    [Catalog Data]      [Photo Library]
    (PostgreSQL)         (Read-only)
```

### Component Responsibilities

**PostgreSQL**
- Catalog metadata (images, duplicates, dates, quality scores)
- Celery task results (for chord operations)
- ACID transactions for data integrity
- Efficient indexing for large datasets

**Redis**
- Celery message broker
- Task queue management
- Real-time job progress tracking
- Fast in-memory operations

**Celery**
- Background job processing
- Parallel task execution
- Duplicate detection coordination
- Thumbnail generation
- Catalog organization

**FastAPI**
- REST API for catalog operations
- Image serving and metadata queries
- Job submission and monitoring
- Real-time SSE progress streams

**Vue.js Frontend**
- Modern SPA interface
- Catalog browsing and filtering
- Duplicate comparison
- Real-time performance monitoring

**GPU (Optional)**
- NVIDIA CUDA for perceptual hashing
- 20-30x faster image processing
- NVIDIA MPS for multi-process sharing
- FAISS for similarity search

---

## Software Stack

### Core Technologies

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Language | Python 3.11+ | Application logic |
| Database | PostgreSQL 14+ | Catalog storage |
| Broker | Redis 7+ | Task queue |
| Task Queue | Celery 5+ | Background jobs |
| Web API | FastAPI | REST endpoints |
| Frontend | Vue.js 3 | User interface |
| GPU | PyTorch + CUDA 12.4 | Acceleration |
| Metadata | ExifTool | EXIF/XMP extraction |

### Python Dependencies

**Core**:
- `pydantic` v2 - Type-safe data models
- `sqlalchemy` - Database ORM
- `pillow` - Image processing
- `pillow-heif` - HEIC/HEIF support

**Web**:
- `fastapi` - Async web framework
- `uvicorn` - ASGI server
- `sse-starlette` - Server-sent events

**CLI**:
- `click` - Command-line framework
- `rich` - Terminal formatting

**Testing**:
- `pytest` - Test framework
- `pytest-xdist` - Parallel test execution
- 642 tests, 79% coverage

---

## Application Architecture

### Module Structure

```
lumina/
├── core/              # Catalog and analysis engine
│   ├── catalog.py     # Catalog management
│   ├── analyzer.py    # Photo analysis pipeline
│   └── organizer.py   # File organization
│
├── db/                # Database layer
│   ├── connection.py  # PostgreSQL connection
│   ├── schema.sql     # Database schema
│   └── config.py      # Database configuration
│
├── jobs/              # Celery background tasks
│   ├── tasks.py       # Job definitions
│   ├── parallel_duplicates.py  # Duplicate detection
│   └── progress_publisher.py   # Job progress tracking
│
├── api/               # FastAPI routes
│   └── routers/
│       ├── catalogs.py    # Catalog endpoints
│       └── images.py      # Image serving
│
├── web/               # Web server
│   ├── main.py        # FastAPI application
│   └── jobs_api.py    # Job management endpoints
│
├── cli/               # Command-line interface
│   ├── analyze.py     # lumina-analyze
│   ├── web.py         # lumina-web
│   └── organize.py    # lumina-organize
│
└── shared/            # Shared utilities
    ├── metadata.py    # Metadata extraction
    ├── perceptual_hash.py  # Image hashing
    └── quality_scorer.py   # Quality assessment
```

---

## Data Model

### Core Entities

**Images**
- `id` (UUID) - Unique identifier
- `catalog_id` - Parent catalog
- `source_path` - Original file location
- `checksum` (SHA-256) - For exact duplicate detection
- `file_type` - image/video
- `metadata` (JSONB) - EXIF, XMP, format, resolution
- `dates` (JSONB) - Extracted dates with confidence levels
- `quality_score` (0-100) - Multi-factor quality assessment
- `status` - active/archived/flagged/rejected/selected

**Duplicate Groups**
- `id` (UUID) - Group identifier
- `catalog_id` - Parent catalog
- `primary_hash` - Representative hash
- `similarity_threshold` - Detection threshold used
- Individual member links via junction table

**Perceptual Hashes**
- `image_id` - Foreign key to images
- `dhash` - Difference hash (64-bit)
- `ahash` - Average hash (64-bit)
- `whash` - Wavelet hash (64-bit)
- Used for similarity detection (Hamming distance)

**Jobs**
- `id` (UUID) - Job identifier
- `job_type` - analyze/organize/duplicates/thumbnails
- `status` - PENDING/PROGRESS/SUCCESS/FAILURE
- `parameters` (JSONB) - Job configuration
- `progress` (JSONB) - Current/total/percent
- Real-time updates via PostgreSQL NOTIFY

---

## Processing Pipeline

### 1. Analysis Phase

```
User Input
    │
    ↓
┌────────────────────┐
│ lumina-analyze CLI │
└────────┬───────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   Multi-Core File Discovery         │
│   - Parallel directory traversal    │
│   - Extension filtering             │
│   - Incremental (skip existing)     │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   Parallel Metadata Extraction      │
│   - ExifTool for EXIF/XMP           │
│   - Date extraction (multi-source)  │
│   - Checksum (SHA-256)              │
│   - Corruption detection            │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   GPU-Accelerated Hashing           │
│   (if --detect-duplicates)          │
│   - Perceptual hashing (dHash...)   │
│   - Quality scoring                 │
│   - 20-30x faster with GPU          │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   PostgreSQL Storage                │
│   - Batch inserts                   │
│   - Transaction safety              │
│   - Index updates                   │
└─────────────────────────────────────┘
```

### 2. Duplicate Detection Phase

```
Trigger: User request or post-analysis
    │
    ↓
┌─────────────────────────────────────┐
│   Celery Job Submission             │
│   - Create job record               │
│   - Queue background task           │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   Build Hash Index (in-memory)      │
│   - Load all perceptual hashes      │
│   - Group by hash similarity        │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   Parallel Hamming Distance         │
│   - Compare hash pairs              │
│   - Threshold filtering (default 5) │
│   - Union-find grouping             │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   Quality-Based Selection           │
│   - Score each image                │
│   - Select best from each group     │
│   - Create duplicate groups         │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   PostgreSQL Storage                │
│   - Save duplicate groups           │
│   - Update image statuses           │
│   - Publish completion              │
└─────────────────────────────────────┘
```

### 3. Organization Phase

```
User specifies output directory
    │
    ↓
┌─────────────────────────────────────┐
│   Generate Organization Plan        │
│   - Date-based directory structure  │
│   - Conflict detection              │
│   - Dry-run preview                 │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   User Review (if conflicts)        │
│   - Show proposed structure         │
│   - Highlight conflicts             │
│   - Request confirmation            │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   Execute Operations                │
│   - Copy or move files              │
│   - Preserve metadata               │
│   - Verify checksums                │
└────────┬────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────┐
│   Update Catalog                    │
│   - New file paths                  │
│   - Status updates                  │
│   - Transaction commit              │
└─────────────────────────────────────┘
```

---

## Performance Characteristics

### Multi-Core Scaling

**CPU Processing**:
- Linear scaling up to core count
- Default: Use all available cores
- Configurable via `WORKERS` environment variable
- Typical: 20-30x speedup on 32-core system

**Memory Usage**:
- ~500 bytes per image record
- 100k images ≈ 50 MB catalog memory
- Perceptual hashes add ~32 bytes per image
- PostgreSQL connection pool: ~10 MB

**Disk I/O**:
- Sequential reads during file discovery
- Random reads for metadata extraction
- Batch writes to PostgreSQL
- Recommend SSD for catalog database

### GPU Acceleration

**With NVIDIA GPU**:
- 20-30x faster perceptual hashing
- Batch processing for efficiency
- NVIDIA MPS for multi-process sharing
- CUDA 12.4 with PyTorch

**Requirements**:
- NVIDIA GPU with 8GB+ VRAM
- CUDA compute capability 7.0+
- nvidia-docker2 for Docker deployment

---

## Real-Time Features

### Job Progress Tracking

**PostgreSQL LISTEN/NOTIFY**:
- Real-time progress updates
- No polling required
- Efficient pub/sub pattern

**Server-Sent Events (SSE)**:
- Live progress streaming to web UI
- Automatic reconnection
- Progress percentage, throughput, ETA

**In-Memory Fallback**:
- Works without PostgreSQL NOTIFY
- Polling-based updates
- 1-second refresh interval

### Performance Monitoring

**Metrics Collected**:
- Images processed per second
- GPU utilization percentage
- Database query performance
- Celery queue depth
- Memory usage trends

**Dashboard**:
- Real-time charts
- Historical trends
- Bottleneck identification
- Resource allocation recommendations

---

## Security & Safety

### File System Safety

**Read-Only Photo Library**:
- Source photos mounted read-only
- No modifications to originals
- Copy/move operations are explicit

**Catalog Integrity**:
- PostgreSQL ACID transactions
- Checksum verification
- Corruption detection
- Automatic recovery

### Input Validation

**Pydantic Models**:
- Type-safe data validation
- Automatic serialization
- Schema enforcement

**Path Safety**:
- Path traversal prevention
- Extension whitelist
- Symbolic link handling

### Network Security

**Web API**:
- CORS disabled by default (localhost only)
- No authentication (designed for local use)
- Read-only image serving
- Rate limiting on expensive operations

**Docker Deployment**:
- Internal PostgreSQL (no external access)
- Internal Redis (no external access)
- Configurable web port binding

---

## Scalability Considerations

### Current Limits

- **Tested**: 1M+ images
- **Database**: PostgreSQL handles billions of rows
- **Memory**: Catalog loaded on-demand, not fully in memory
- **Disk**: Scales with photo library size

### Performance Tuning

**Small Libraries** (<10k images):
- 4-8 CPU workers
- 2-4 Celery workers
- GPU optional

**Medium Libraries** (10k-100k):
- 16-32 CPU workers
- 4-8 Celery workers
- GPU recommended

**Large Libraries** (100k+):
- 32-64 CPU workers
- 8-16 Celery workers
- GPU strongly recommended
- SSD for catalog database

---

## Future Architecture

### Potential Enhancements

**Distributed Processing**:
- Remote worker support
- Cloud storage integration
- Distributed duplicate detection

**Advanced Features**:
- AI-powered image tagging
- Face recognition
- Scene detection
- Smart collections

**Scalability**:
- Lazy loading for massive catalogs
- Distributed hash tables
- Caching layers (Redis)
- Read replicas for PostgreSQL

---

## Development

### Running Locally

See **[Development Guide](./DEVELOPMENT.md)** for:
- Native Python setup
- Database configuration
- Running tests
- Code quality checks

### Testing

**Test Coverage**: 642 tests, 79% coverage

**Test Categories**:
- Unit tests (fast, no external dependencies)
- Integration tests (PostgreSQL required)
- API tests (FastAPI endpoints)
- CLI tests (command-line interface)

### Contributing

See **[Contributing Guide](../guides/CONTRIBUTING.md)** for:
- Development workflow
- Code style standards
- Pull request process
- Architecture decisions

---

## References

- **[Quick Start](../guides/QUICK_START.md)** - Get running in 5 minutes
- **[Docker Deployment](../deployment/DOCKER.md)** - Production setup
- **[Configuration](../deployment/CONFIGURATION.md)** - All options
- **[Development](./DEVELOPMENT.md)** - Developer setup
