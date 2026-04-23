# Lumina User Guide

## Table of Contents

- [Getting Started](#getting-started)
- [Web Interface](#web-interface)
- [Background Jobs](#background-jobs)
- [Duplicate Detection and Review](#duplicate-detection-and-review)
- [Burst Management](#burst-management)
- [Event Detection](#event-detection)
- [Image Classification and Tagging](#image-classification-and-tagging)
- [File Organization](#file-organization)
- [REST API Reference](#rest-api-reference)
- [Troubleshooting](#troubleshooting)

---

## Getting Started

### Docker (Recommended)

```bash
git clone https://github.com/irjudson/lumina.git
cd lumina
cp .env.example .env
# Edit .env: set CATALOG_PATH and PHOTOS_PATH
docker compose up -d
open http://localhost:8765
```

Lumina creates a default catalog called "My Photos" on first start and mounts your photo library read-only.

### Native Python

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Start the API server
lumina-web
```

Then open http://localhost:8765.

### System Requirements

- Python 3.11+
- PostgreSQL 14+ with pgvector extension
- ExifTool (for metadata extraction)
- Optional: Ollama (for AI classification and tagging)
- Optional: NVIDIA GPU with CUDA 12.4 (for 20-30x faster hashing)

Install ExifTool:
```bash
# macOS
brew install exiftool

# Ubuntu/Debian
sudo apt-get install libimage-exiftool-perl
```

---

## Web Interface

Access Lumina at http://localhost:8765. The interface has a three-panel layout:

- **Left sidebar** — Navigation and filters
- **Center** — Image grid or view content
- **Right** — Image metadata and details

### Library View

The main image grid. Use the left sidebar to navigate:

**Library section** (always visible):
- All Photos
- Images only
- Videos only
- No Date
- Suspicious Dates
- Rejected / Archived

**Smart Views** (collapsible):
- Duplicates — images flagged as duplicate candidates
- Bursts — rapid-fire sequence images
- Events — GPS-clustered photographic events
- Timeline — chronological browsing
- Map — geographic map of GPS-tagged images
- Collections — smart groupings

**Filter by Tag** (collapsible):
- Browse all tags applied to images
- Click any tag to filter the grid
- Multiple tags can be selected

### Image Cards

Each card shows a thumbnail. On hover:
- Primary tag is shown at the bottom
- Content class badge (screenshot, document, etc.) shown if classified

Click a card to open the detail overlay with full metadata, all extracted dates, EXIF data, and quality score.

### Filtering and Sorting

The toolbar above the grid lets you:
- Filter by file type, status, content class, date quality
- Sort by date, path, or file size (ascending or descending)
- Switch between infinite scroll and paginated modes

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `R` | Refresh |
| `S` | Toggle scroll / page mode |
| `← / →` | Previous / next page (page mode) |
| `H / L` | Previous / next page (Vim-style) |
| `Esc` | Close overlay |

---

## Background Jobs

All long-running operations run as background jobs. Submit them from the **Quick Actions** panel in the library view, or from the Settings page for a specific catalog.

Jobs update their progress in real time — a progress bar appears in the UI while any job is running.

### Job Types

| Job | What it does |
|-----|-------------|
| **Scan** | Discover files, extract EXIF/XMP metadata, compute checksums |
| **Extract Metadata Columns** | Populate typed database columns (capture_time, GPS, camera, etc.) from JSONB metadata — run after every scan |
| **Hash Images** | Compute perceptual hashes (dHash, aHash, wHash, dhash_16) |
| **Find Duplicates** | Run five-layer duplicate detection pipeline |
| **Auto-Resolve Duplicates** | Automatically resolve zero-hamming duplicate pairs using quality rules |
| **Generate Thumbnails** | Create image thumbnails for the web UI |
| **Detect Bursts** | Group rapid-fire sequences and select the best shot |
| **Detect Events** | Cluster GPS images by time and location into photographic events |
| **Classify Images** | Label images as photo, screenshot, document, etc. |
| **Auto-Tag** | Generate descriptive tags via OpenCLIP (GPU) or Ollama VLM |
| **Organize** | Reorganize files into a date-based directory structure |

### Recommended Workflow for a New Library

1. **Scan** — builds the catalog
2. **Extract Metadata Columns** — populates typed columns needed by downstream jobs
3. **Hash Images** — required before duplicate detection
4. **Find Duplicates** — surfaces duplicate candidates
5. **Generate Thumbnails** — enables image previews
6. **Detect Bursts** — optional; requires metadata columns
7. **Detect Events** — optional; requires GPS data and metadata columns
8. **Classify Images** — optional; labels content type
9. **Auto-Tag** — optional; requires OpenCLIP or Ollama
10. **Organize** — optional; moves/copies files to date structure

### Cancelling Jobs

Click the **Cancel** button in the progress panel. Most jobs check for cancellation at regular intervals and stop cleanly.

---

## Duplicate Detection and Review

### How Detection Works

Lumina uses a five-layer pipeline to find duplicates at different levels of similarity:

| Layer | What it finds |
|-------|--------------|
| L1 Exact | Identical file content (same SHA-256 checksum) |
| L2 Re-import | Same image exported or copied to a new path |
| L3 Format variant | Same image saved as JPEG + HEIC, or RAW + JPEG |
| L4 Preview-scale | Full-resolution vs. embedded preview/thumbnail |
| L5 Near-duplicate | Perceptually similar images (edited, cropped, recompressed) |

### Reviewing Candidates

Navigate to **Duplicates** in the Smart Views section. Each card shows a pair of images with:
- Their similarity score and detection layer
- File size, resolution, and format for each
- A suggested primary (the one to keep)

**Decisions:**
- **Keep this one** — marks the selected image as primary; the other is archived
- **Keep both** — dismisses the pair without archiving either
- **Skip** — moves to the next pair without deciding

### Auto-Resolve

For zero-hamming duplicate pairs (pixel-identical content), use **Auto-Resolve Duplicates** from Quick Actions. It applies deterministic quality rules without requiring manual review:

1. Format tier: RAW > TIFF > HEIC > JPEG > PNG (format_variant layer only)
2. Resolution: higher pixel count wins
3. File size: files >5% larger are preferred (better compression retained)
4. Filename: timestamp-based names preferred over generic `IMG_NNNN`
5. Tiebreak: larger file size

Resolved pairs get a decision record, the loser is archived, and a suppression pair is recorded to prevent re-surfacing.

### Viewing Duplicate Statistics

The Duplicates view shows a breakdown by layer, total candidate count, and how many have been reviewed vs. pending.

---

## Burst Management

### What is a Burst?

A burst is a rapid sequence of photos taken within a short time window (e.g., holding the shutter button, sports photography, timelapse). Lumina groups these sequences and selects the best shot based on quality score.

### Detecting Bursts

Run **Detect Bursts** from Quick Actions. Default parameters:
- Gap threshold: 1 second between shots
- Minimum burst size: 3 images

### Reviewing Bursts

Navigate to **Bursts** in Smart Views. Each burst shows:
- All images in the sequence with timestamps
- Quality scores for each
- The automatically selected best shot (highlighted)

You can override the selection by clicking a different image in the sequence.

---

## Event Detection

### What is an Event?

An event is a cluster of GPS-tagged photos taken within a small geographic area during a continuous time window — a birthday party, hike, sports game, vacation day.

### Detecting Events

Run **Detect Events** from Quick Actions. Default parameters:
- Max radius: 0.402 km (0.25 miles)
- Max time gap: 2 hours between consecutive shots
- Minimum images: 10
- Minimum duration: 1 hour

Events are scored by density (images per hour) and compactness (tighter radius = higher score). Results replace any previous event detection run.

### Browsing Events

Navigate to **Events** in Smart Views. Events are listed by score (highest first). Each event card shows:
- Date range and duration
- Image count and geographic radius
- Score

Click an event to expand it and see a thumbnail grid of all images in the cluster.

---

## Image Classification and Tagging

### Classification

**Classify Images** labels each image with a content type:

| Class | Description |
|-------|-------------|
| `photo` | Real-world photograph |
| `screenshot` | Screen capture from phone, computer, or app |
| `document` | Scanned/photographed document, receipt, form |
| `social_media` | Image with overlaid UI, text, or watermarks |
| `artwork` | Digital art, illustration, graphic design |
| `other` | Animated GIF, icon, unclassifiable |
| `invalid` | Corrupt file, too small to be a real photo |
| `unknown` | Heuristics undecided (use VLM to resolve) |

Classification uses fast PIL heuristics first (checking dimensions, aspect ratios, known screen resolutions, animated GIFs). Images heuristics can't classify are either left as `unknown` or sent to an Ollama VLM if `use_vlm=true` is set.

Content class badges appear on image cards in the library view.

### Auto-Tagging

**Auto-Tag** generates descriptive tags for your images. Two backends are available:

**OpenCLIP** (recommended for large libraries):
- GPU-accelerated batch processing
- Generates tag probabilities against a fixed vocabulary
- Fast: hundreds of images per minute with a GPU

**Ollama** (more descriptive):
- Uses a local vision language model (e.g., llava)
- Sequential per-image processing
- More flexible, natural-language tags

Tags appear in the **Filter by Tag** sidebar section and on image card hover (primary tag).

---

## File Organization

### Overview

The **Organize** job reorganizes your library into a predictable date-based directory structure:

```
<output_directory>/
  2023/06-15/20230615_142300.jpg      ← resolved (EXIF with time)
  2023/06-15/20230615_142301.jpg
  _date_only/2023/06-15/              ← date known, time is midnight
  _rejected/2023/06-15/               ← rejected images
  _archived/2023/06-15/               ← archived images
  _unresolved/unknown/                ← no usable date
```

### Date Confidence Tiers

Files are placed into subdirectories based on date confidence:

| Tier | Condition | Location |
|------|-----------|----------|
| `resolved` | EXIF DateTimeOriginal with real time | Primary tree `YYYY/MM-DD/` |
| `iffy` | Filename, directory, or EXIF ModifyDate | Primary tree `YYYY/MM-DD/` |
| `date_only` | Any source where time is midnight | `_date_only/YYYY/MM-DD/` |
| `unresolved` | No usable date found | `_unresolved/unknown/` |

### Scope Options

| Scope | What gets organized |
|-------|-------------------|
| `new` (default) | Only images not yet organized |
| `resolved_only` | Only images with fully resolved EXIF dates |
| `all` | All images regardless of prior organization |

### Dry Run

Always preview before executing:

1. In Quick Actions, select **Organize (Preview)** — this runs the job with `dry_run=true`
2. Review the summary: how many files will move, how many collisions, storage required
3. If satisfied, run **Organize** with `dry_run=false`

### Safety

- Source files are never deleted without a verified checksum match at the destination
- Collision resolution adds a `_01`, `_02`, ... suffix automatically
- Excluded paths: anything containing `#recycle` or `Possible Duplicate`
- The job tracks `organized_path` in the database; re-running with `scope=new` skips already-organized files

---

## REST API Reference

All endpoints are under `/api/`.

### Catalogs

```
GET    /api/catalogs                          List all catalogs
POST   /api/catalogs                          Create a catalog
GET    /api/catalogs/{id}                     Get catalog details
PATCH  /api/catalogs/{id}                     Update catalog settings
DELETE /api/catalogs/{id}                     Delete a catalog

GET    /api/catalogs/{id}/images              List images (paginated)
GET    /api/catalogs/{id}/images/{img_id}     Get image metadata
GET    /api/catalogs/{id}/images/{img_id}/thumbnail  Get thumbnail

GET    /api/catalogs/{id}/smart-counts        Count images per smart view
GET    /api/catalogs/{id}/tags                List all tags
GET    /api/catalogs/{id}/events              List events (sorted by score)
GET    /api/catalogs/{id}/events/{ev_id}/images  Images in an event

GET    /api/catalogs/{id}/bursts              List burst sequences
GET    /api/catalogs/{id}/bursts/{burst_id}   Get burst details
POST   /api/catalogs/{id}/bursts/{burst_id}/select  Set best shot
```

### Jobs

```
POST   /api/catalogs/{id}/jobs                Submit a job
GET    /api/jobs/{job_id}                     Get job status
POST   /api/jobs/{job_id}/cancel              Cancel a running job
GET    /api/catalogs/{id}/jobs                List recent jobs
```

### Duplicates

```
GET    /api/catalogs/{id}/duplicates/candidates          List candidate pairs
POST   /api/catalogs/{id}/duplicates/candidates/{c}/decide  Record a decision
GET    /api/catalogs/{id}/duplicates/stats               Counts by layer
GET    /api/catalogs/{id}/duplicates/groups              Duplicate groups (legacy)
```

### Example: Submit a Scan Job

```bash
curl -X POST http://localhost:8765/api/catalogs/{catalog_id}/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "scan"}'
```

Response:
```json
{
  "job_id": "abc123",
  "status": "pending",
  "message": "Job queued"
}
```

### Example: List Events

```bash
curl "http://localhost:8765/api/catalogs/{catalog_id}/events?limit=20&offset=0"
```

Response:
```json
{
  "events": [
    {
      "id": "...",
      "start_time": "2023-06-15T10:00:00",
      "end_time": "2023-06-15T14:30:00",
      "duration_minutes": 270,
      "image_count": 148,
      "center_lat": 37.7749,
      "center_lon": -122.4194,
      "radius_km": 0.31,
      "score": 22.4
    }
  ],
  "total": 176
}
```

---

## Troubleshooting

### No images visible after scan

Run **Extract Metadata Columns** after scanning — this populates the typed database columns used by most queries and filters.

### Thumbnails not showing

Run **Generate Thumbnails** from Quick Actions. Thumbnails are generated into the catalog's storage directory and served by the API.

### Events not appearing

Events require:
1. Images with GPS coordinates (`latitude`/`longitude` columns populated)
2. Images with a valid `capture_time` (run Extract Metadata Columns first)
3. At least `min_images` (default 10) GPS images within the radius and time window

### Classify Images returns mostly `unknown`

By default, classification only uses heuristics. To use the Ollama VLM for images heuristics can't classify, set `use_vlm=true` in the job parameters and ensure Ollama is running at `OLLAMA_HOST`.

### Auto-Tag produces no results

OpenCLIP requires `open-clip-torch` to be installed. Ollama requires a running Ollama instance with a vision model (e.g., `llava`). Check the job result for the specific error.

### Organize job: "No organized_directory configured"

Set the **Organized Directory** path in catalog Settings before running the organize job.

### Port already in use

```bash
lumina-web --port 8080
```

Or in Docker, change `WEB_PORT` in `.env`.

### HEIC files not processing

Ensure `pillow-heif` is installed:
```bash
pip install pillow-heif
```

### ExifTool not found

```bash
# macOS
brew install exiftool

# Ubuntu/Debian
sudo apt-get install libimage-exiftool-perl

# Verify
which exiftool
exiftool -ver
```

---

## Safety and Data Protection

- **Source files are never modified** during scanning, hashing, classification, or tagging
- **Organization** requires explicit configuration of an output directory; the source is not touched
- **Copy mode** (default for Organize) leaves originals in place; checksums verified at destination before updating the catalog
- **Move mode** deletes the source only after a verified checksum match
- **Dry run** previews any organize operation before executing it
- **Rejected / archived** images remain on disk; only their status in the catalog changes
