# Lumina Architecture

Photo and video library management system with multi-layer duplicate detection, AI-powered analysis, and event clustering.

## Overview

Lumina is designed for managing large photo libraries (100k–1M+ images) with:
- **Zero data loss** — All operations on source files are read-only; organization uses copy or verified move
- **High performance** — Multi-core CPU + optional GPU acceleration (20-30x for perceptual hashing)
- **Intelligent analysis** — Metadata extraction, five-layer duplicate detection, AI classification, event detection
- **Simple deployment** — Single Docker container with all services

---

## Deployment Architecture

### Single-Container Design

```
┌─────────────────────────────────────────────────────────┐
│                   Lumina Container                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  PostgreSQL  │  │   FastAPI    │  │ Thread Pool  │ │
│  │  + pgvector  │  │   Web API    │  │  Job System  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐                   │
│  │   Vue.js 3   │  │     GPU      │                   │
│  │   Frontend   │  │  (optional)  │                   │
│  └──────────────┘  └──────────────┘                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
           │                    │
           ↓                    ↓
    [Catalog Data]      [Photo Library]
    (PostgreSQL)         (Read-only)
```

### Component Responsibilities

**PostgreSQL + pgvector**
- Catalog metadata: images, tags, duplicates, bursts, events
- Job coordination, progress tracking, and history
- CLIP embedding storage for semantic similarity search
- ACID transactions for data integrity

**Thread Pool Job System**
- Background job processing via `ThreadPoolExecutor`
- All jobs run sequentially within a catalog to avoid contention
- Jobs: scan, hash, dedup, thumbnails, bursts, events, classify, tag, organize
- Cooperative cancellation support per job

**FastAPI**
- REST API for all catalog operations
- Server-sent events (SSE) for real-time job progress streaming
- Image thumbnail serving
- Job submission and status monitoring

**Vue.js 3 Frontend**
- Single-page application with Pinia state management
- Views: Library, Duplicates, Bursts, Events, Timeline, Map, Collections, Settings
- Tag browser with live filtering
- Real-time progress updates via SSE

**GPU (Optional)**
- NVIDIA CUDA for perceptual hashing (20-30x faster)
- CLIP embedding computation (OpenCLIP)
- NVIDIA MPS for multi-process sharing

---

## Software Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Language | Python 3.11+ | Application logic |
| Database | PostgreSQL 14+ | Catalog storage |
| Vector search | pgvector | CLIP embedding similarity |
| Job system | ThreadPoolExecutor | Background jobs |
| Web API | FastAPI | REST + SSE endpoints |
| Frontend | Vue.js 3 + Tailwind CSS | User interface |
| State | Pinia | Frontend state management |
| GPU | PyTorch + CUDA 12.4 | Hashing + embeddings |
| Metadata | ExifTool | EXIF/XMP extraction |
| VLM | Ollama | Image classification + tagging |
| Embeddings | open-clip-torch | CLIP tag generation |

---

## Module Structure

```
lumina/
├── analysis/              # Image analysis algorithms
│   ├── scanner.py         # File discovery and metadata extraction
│   ├── burst_detector.py  # Burst sequence detection
│   ├── image_classifier.py # Heuristic + VLM content classification
│   ├── image_tagger.py    # OpenCLIP + Ollama auto-tagging
│   ├── quality_scorer.py  # Multi-factor quality assessment
│   ├── semantic_search.py # CLIP embedding similarity
│   └── dedup/             # Five-layer duplicate detection pipeline
│       ├── pipeline.py
│       ├── layers/
│       │   ├── l1_exact.py          # Checksum exact match
│       │   ├── l2_reimport.py       # Re-import detection
│       │   ├── l3_format_variant.py # Same image, different format
│       │   ├── l4_preview.py        # Preview-scale detection
│       │   └── l5_near_duplicate.py # Perceptual near-duplicate
│       └── archive.py     # Archiving resolved duplicates
│
├── api/                   # FastAPI application
│   ├── app.py             # Application factory
│   └── routers/
│       ├── catalogs.py    # Catalog, image, burst, event, tag endpoints
│       ├── duplicates.py  # Duplicate review and decision endpoints
│       ├── jobs_new.py    # Job submission and monitoring
│       ├── collections.py # Smart collections
│       └── warehouse.py   # Warehouse scheduler endpoints
│
├── db/                    # Database layer
│   ├── connection.py      # PostgreSQL connection pool + init_db
│   ├── models.py          # SQLAlchemy ORM models
│   ├── catalog_schema.py  # Schema creation helpers
│   └── migrations/        # Idempotent schema migrations
│       ├── content_class.py
│       ├── events_schema.py
│       └── organized_path.py
│
├── jobs/                  # Background job system
│   ├── background_jobs.py # ThreadPoolExecutor coordination
│   ├── job_implementations.py # All job execution logic
│   ├── framework.py       # ParallelJob definition framework
│   ├── definitions/       # Registered job types
│   │   ├── scan.py
│   │   ├── hash_v2.py
│   │   ├── detect_duplicates_v2.py
│   │   ├── bursts.py
│   │   └── organize.py
│   ├── tag_storage.py     # Tag persistence helpers
│   └── warehouse_scheduler.py # Automated job scheduling
│
├── cli/                   # Command-line interface
│   ├── analyze.py         # lumina-analyze
│   ├── web.py             # lumina-web
│   ├── organize.py        # lumina-organize
│   └── server.py          # lumina-server
│
└── shared/                # Shared utilities
    ├── media_utils.py     # Checksum, file type detection
    └── thumbnail_utils.py # Thumbnail generation
```

---

## Data Model

### Core Entities

**images**
- `id` (VARCHAR) — Checksum-based identifier
- `catalog_id` (UUID) — Parent catalog
- `source_path` — Original file location (read-only)
- `checksum` (SHA-256) — Exact duplicate detection
- `file_type` — image / video
- `status_id` — active / rejected / archived / flagged
- `metadata` (JSONB) — Raw EXIF/XMP data
- `dates` (JSONB) — Extracted dates with confidence and source
- `capture_time` — Typed datetime column (populated by extract_metadata_columns)
- `capture_time_source` — Which source provided the date
- `quality_score` (0-100) — Multi-factor quality assessment
- `content_class` — photo / screenshot / document / social_media / artwork / other / invalid
- `organized_path` — Destination path after file organization
- `dhash`, `ahash`, `whash` — 64-bit perceptual hashes
- `dhash_16` — 256-bit high-resolution perceptual hash
- `latitude`, `longitude` — GPS coordinates (typed columns)
- `geohash_4/6/8` — Spatial indexing
- `clip_embedding` (vector) — CLIP semantic embedding

**duplicate_candidates**
- `id` (UUID) — Candidate pair identifier
- `catalog_id`, `image_id_a`, `image_id_b`
- `layer` — Detection layer that found this pair
- `confidence` — Similarity score
- `detection_meta` (JSONB) — Hamming distance, hashes used
- `reviewed_at` — Set when a decision is recorded

**duplicate_decisions**
- Records accept/reject decisions per candidate pair
- Links to `primary_id` (the image to keep)

**suppression_pairs**
- Prevents re-surfacing already-reviewed pairs

**bursts**
- `id`, `catalog_id`, `image_count`, `start_time`, `end_time`
- `best_image_id` — Selected best shot

**events**
- `id`, `catalog_id`
- `start_time`, `end_time`, `duration_minutes`
- `image_count`, `center_lat`, `center_lon`, `radius_km`
- `score` — Density × spatial bonus (images/hour / (1 + radius_km))

**tags** / **image_tags**
- Per-catalog tag vocabulary with confidence and source

**jobs**
- `id` (UUID), `catalog_id`, `job_type`
- `status` — PENDING / PROGRESS / SUCCESS / FAILURE / CANCELLED
- `parameters` (JSONB) — Job configuration
- `progress` (JSONB) — current/total/percent/phase/message
- `result` (JSONB) — Final result or error

---

## Processing Pipelines

### Scan Pipeline

```
Source directories
    │
    ↓
Parallel file discovery (incremental, skips known checksums)
    │
    ↓
Metadata extraction (ExifTool: EXIF, XMP, GPS)
    │
    ↓
Date resolution (EXIF → filename → directory → filesystem)
    │
    ↓
Quality scoring + perceptual hashing
    │
    ↓
PostgreSQL batch insert
```

### Five-Layer Duplicate Detection

After hashing, `detect_duplicates_v2` runs five detection layers in sequence. Each layer finds candidate pairs; layers don't overlap:

```
L1  Exact match          — identical SHA-256 checksums
L2  Re-import detection  — same content, different path (post-export duplicates)
L3  Format variant       — same image in different formats (JPEG + HEIC, RAW + JPEG)
L4  Preview-scale        — full-res vs thumbnail/preview version
L5  Near-duplicate       — perceptual match via dhash_16 Hamming distance
```

Each detected pair becomes a `duplicate_candidate`. The review UI surfaces them for user decisions or auto-resolution.

### Auto-Resolve Pipeline

`auto_resolve_duplicates` applies deterministic quality rules to unreviewed candidates with hamming=0:

```
1. Format tier:     RAW > TIFF > HEIC > JPEG > PNG  (format_variant layer only)
2. Resolution:      Higher pixel count wins
3. File size:       >5% difference → larger file wins (better compression retained)
4. Filename score:  Timestamp-based filenames preferred over IMG_NNNN generics
5. Tiebreak:        Larger file
```

For each resolved pair: writes a `duplicate_decision`, marks the pair reviewed, adds a `suppression_pair`, archives the loser.

### Event Detection Pipeline

`detect_events` clusters GPS-tagged images by time and space:

```
1. Load all active images with GPS + date, sorted by date
2. Union-find: connect consecutive images if
   - time gap < max_gap_hours (default 2h)
   - haversine distance < max_radius_km (default 0.402 km = 0.25 miles)
3. Filter clusters by min_images (default 10) and min_duration_hours (default 1h)
4. Score: (images / max(duration_h, 0.25)) × (1 / (1 + radius_km))
5. Write to events + event_images tables (clears previous results first)
```

### Image Classification

`classify_images` uses a two-tier approach:

**Tier 1 — Heuristics (always runs, very fast):**
- PIL validation → `invalid` if unreadable
- ≤64px either dimension → `invalid`
- Animated GIF → `other`
- Exact device screen resolution (iPhone, Android, desktop) → `screenshot`
- Aspect ratio > 3.5:1 → `screenshot`
- Otherwise → `unknown`

**Tier 2 — Ollama VLM (optional, `use_vlm=True`):**
- Runs only on images heuristics couldn't classify
- Model: `qwen3-vl` (configurable)
- Categories: photo, screenshot, document, social_media, artwork, other

### File Organization

`organize` plans a date-based output structure before touching any files:

```
<organized_directory>/
  YYYY/MM-DD/YYYYMMDD_HHMMSS[_NN].ext   ← resolved + iffy
  _date_only/YYYY/MM-DD/                ← midnight timestamps
  _rejected/YYYY/MM-DD/                 ← rejected images
  _archived/YYYY/MM-DD/                 ← archived images
  _unresolved/unknown/                  ← no usable date
```

Confidence tiers:
- `resolved` — EXIF DateTimeOriginal with real time component
- `iffy` — filename, directory, filesystem, or EXIF ModifyDate
- `date_only` — any source with synthetic midnight 00:00:00
- `unresolved` — no date found

Dry-run mode plans without executing; checksums verified after every copy/move.

---

## Performance

### CPU Scaling
- File discovery: parallel across directories
- Metadata extraction: sequential per file (ExifTool subprocess)
- Hashing: parallel batch processing
- Duplicate detection: sequential (single-threaded by design to avoid race conditions)

### GPU Acceleration
- Perceptual hashing: 20-30x faster with CUDA
- CLIP embeddings: batch GPU inference
- Requires NVIDIA GPU, 8GB+ VRAM, CUDA compute ≥ 7.0

### Memory
- ~500 bytes per image in PostgreSQL
- 100k images ≈ 50 MB catalog memory
- CLIP embeddings: 512 float32 per image ≈ 200 MB for 100k images

### Tested Scale
- 1M+ images in a single catalog
- PostgreSQL handles billions of rows
- pgvector supports approximate nearest-neighbor at scale

---

## Security & Safety

- **Read-only source photos** — source library is never modified unless organize is explicitly run with `operation=move`
- **Checksum verification** — every copy/move is verified against the original checksum before updating the database
- **ACID transactions** — all catalog updates are transactional; failures leave no partial state
- **No authentication** — designed for local/trusted network use; no external access by default
- **Path traversal prevention** — all paths validated before use

---

## Testing

**724 tests** across:
- Unit tests — algorithms tested without external dependencies (haversine, union-find, heuristics, pick_primary logic)
- Integration tests — full API and database tests with PostgreSQL (requires `pytest -m integration`)
- Job tests — job framework, executor, hash computation
- Analysis tests — scanner, duplicate detector, burst detector

```bash
# Unit tests only (no DB required)
pytest -m "not integration"

# All tests (requires running PostgreSQL)
pytest

# With coverage
pytest --cov=lumina --cov-report=term
```

---

## References

- **[Quick Start](../guides/QUICK_START.md)** — Get running in 5 minutes
- **[User Guide](../guides/USER_GUIDE.md)** — Complete feature documentation
- **[Docker Deployment](../deployment/DOCKER.md)** — Production setup
- **[Configuration](../deployment/CONFIGURATION.md)** — All options
- **[Development](./DEVELOPMENT.md)** — Developer setup
