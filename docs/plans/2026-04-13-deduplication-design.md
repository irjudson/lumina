# Layered Deduplication System — Design

**Date:** 2026-04-13  
**Status:** Approved, pending implementation  
**Branch:** feature/ui-2.0

---

## Goals

- Detect duplicates across five distinct relationship types: exact copies, re-imports, format variants (RAW+JPEG), previews/derivatives, and near-duplicates
- Never auto-resolve — all candidates surface to a review queue for user decision
- Never delete — confirmed duplicates move to a provenance-tracked archive table
- Learn from user decisions: suppression prevents re-surfacing reviewed pairs; threshold adaptation makes future detection more accurate
- Reprocess incrementally as the library grows and thresholds evolve

---

## Key Constraints

- Source files are never modified, moved, or deleted
- Every archive action is backed by a `duplicate_decisions` row — full provenance chain
- Small images (<1MP) require 2+ corroborating signals and are hard-capped at 0.65 confidence — always reviewed one at a time with explicit acknowledgment
- Threshold drift never touches reviewed decisions or suppressed pairs

---

## Layer Model

Five layers, ordered cheapest to most expensive. Each runs independently and produces `(image_id_a, image_id_b, layer, confidence, metadata)` candidate pairs.

| Layer | Name | Primary Signal | Complexity |
|---|---|---|---|
| L1 | `exact` | SHA-256 checksum match | O(n) index lookup |
| L2 | `reimport` | Same `source_path`, different row | O(n) index lookup |
| L3 | `format_variant` | Same shot, different format | O(n log n) group-by |
| L4 | `preview` | Scale-invariant visual hash match | O(n²) with size-band pruning |
| L5 | `near_duplicate` | Perceptual hash within adaptive threshold | O(n log n) BK-tree |

**L1 — Exact:** Byte-for-byte identical files. Confidence: 1.0. No threshold.

**L2 — Reimport:** Same physical file scanned multiple times. `detection_meta` records scan timestamps so the user can see when each import occurred. Confidence: 1.0.

**L3 — Format Variant:** Groups by `(floor(capture_time, 1s), camera_make, camera_model)`. Flags groups with heterogeneous `format` values. Confirmed with perceptual hash. Catches RAW+JPEG camera pairs, RAW+TIFF exports.

**L4 — Preview:** Multi-resolution hash comparison with scale awareness. Catches Lightroom previews, Capture One proxies, JPEG exports, app caches — with arbitrary names and paths.

**L5 — Near Duplicate:** BK-tree over `dhash_8` values. Catches processed versions, slight crops, re-exports with adjustments. Threshold is adaptive per catalog.

---

## Data Model

### New tables

**`duplicate_candidates`** — raw pipeline output, one row per pair per layer:
```sql
id              UUID PRIMARY KEY
catalog_id      UUID REFERENCES catalogs ON DELETE CASCADE
image_id_a      TEXT REFERENCES images   -- larger/better file
image_id_b      TEXT REFERENCES images   -- candidate to archive
layer           TEXT CHECK (layer IN ('exact','reimport','format_variant','preview','near_duplicate'))
confidence      FLOAT                    -- 0.0–1.0
verify_carefully BOOLEAN DEFAULT FALSE
verify_reason   TEXT
detection_meta  JSONB                    -- hamming distance, scale ratio, corroborating signals, etc.
created_at      TIMESTAMPTZ DEFAULT now()
reviewed_at     TIMESTAMPTZ
UNIQUE (image_id_a, image_id_b, layer)
```

**`duplicate_decisions`** — immutable audit log of every user action:
```sql
id              UUID PRIMARY KEY
candidate_id    UUID REFERENCES duplicate_candidates
decision        TEXT CHECK (decision IN ('confirmed_duplicate','not_duplicate','deferred'))
primary_id      TEXT REFERENCES images   -- which image survives (null if not_duplicate)
decided_at      TIMESTAMPTZ DEFAULT now()
notes           TEXT
```

**`archived_images`** — full copy of the `images` row at archive time, plus provenance:
```sql
-- all columns from images table, plus:
archived_at         TIMESTAMPTZ DEFAULT now()
archive_reason      TEXT  -- mirrors layer name
decision_id         UUID REFERENCES duplicate_decisions
primary_image_id    TEXT  -- the image that replaced this one
original_catalog_id UUID
restoration_path    TEXT  -- file path, for restoration reference
```

**`detection_thresholds`** — per-catalog per-layer learning state:
```sql
catalog_id      UUID REFERENCES catalogs
layer           TEXT
threshold       FLOAT        -- current operative value
confirmed_count INT DEFAULT 0
rejected_count  INT DEFAULT 0
last_run_threshold FLOAT     -- threshold at last pipeline run, for drift detection
last_updated    TIMESTAMPTZ
PRIMARY KEY (catalog_id, layer)
```

Default starting thresholds:
| Layer | Default | Bounds |
|---|---|---|
| `format_variant` | hamming ≤ 4 | [0, 4] |
| `preview` | hamming ≤ 3 | [1, 6] |
| `near_duplicate` | hamming ≤ 8 | [2, 12] |

**`suppression_pairs`** — permanent do-not-resurface index:
```sql
id_a        TEXT   -- lexicographically smaller of the two image IDs
id_b        TEXT   -- lexicographically larger
decision    TEXT   -- confirmed_duplicate or not_duplicate
created_at  TIMESTAMPTZ DEFAULT now()
PRIMARY KEY (id_a, id_b)
```

### Extensions to `images`

```sql
-- Multi-resolution hashes for L4 scale-invariant detection
dhash_16    TEXT   -- 256-bit hash, detects previews down to ~25% linear scale
dhash_32    TEXT   -- 1024-bit hash, detects previews down to ~12% linear scale
```

The existing `dhash` column is the 64-bit `dhash_8` — used for L5. `dhash_16` and `dhash_32` are computed at import time alongside existing hashes.

---

## Detection Pipeline

Each layer is a pure function: `(catalog_id, thresholds, session) → List[CandidatePair]`. The orchestrator runs layers in order, checks suppression before inserting, and uses `ON CONFLICT DO UPDATE` so re-runs refresh confidence scores without duplicating rows.

```python
LAYERS = [exact, reimport, format_variant, preview, near_duplicate]

def run_pipeline(catalog_id, session):
    thresholds = load_thresholds(catalog_id, session)
    suppressed = load_suppression_set(catalog_id, session)

    for layer_fn in LAYERS:
        for candidate in layer_fn(catalog_id, thresholds, session):
            pair = (min(candidate.a, candidate.b), max(candidate.a, candidate.b))
            if pair not in suppressed:
                upsert_candidate(candidate, session)
```

### L3 — Format Variant

```sql
SELECT id, format, dhash, capture_time, camera_make, camera_model
FROM images
WHERE catalog_id = :cid AND capture_time IS NOT NULL AND camera_make IS NOT NULL
```

Group in Python by `(floor(capture_time, 1s), camera_make, camera_model)`. Flag groups with >1 distinct `format`. Confirm with `hamming(dhash_a, dhash_b) ≤ threshold`.

### L4 — Preview Detection

```python
SMALL_IMAGE_PIXELS = 1_000_000  # 1MP safety threshold

CORROBORATING_SIGNALS = [
    lambda s, _: any(p in s.source_path for p in ['/Previews/', '/.lrdata/', '/cache/', '/Thumbs/']),
    lambda s, _: any(s.source_path.endswith(ext) for ext in ['.lrprev']),
    lambda s, _: re.search(r'_(preview|thumb|sm|proxy)\b', s.source_path, re.I),
    lambda s, l: s.metadata_json.get('exif_stripped') or s.capture_time != l.capture_time,
    lambda s, l: s.created_at > l.capture_time + timedelta(minutes=5),
    lambda s, l: l.format in ('raw', 'arw', 'cr2', 'cr3', 'nef', 'dng') and s.format == 'jpeg',
]

def detect_previews(images, threshold):
    by_size = sorted(images, key=lambda i: (i.width or 0) * (i.height or 0), reverse=True)

    for large in by_size:
        for small in size_band_candidates(large, min_ratio=0.05, max_ratio=0.95):
            scale = sqrt((small.width * small.height) / (large.width * large.height))

            if scale > 0.5:
                dist = hamming(large.dhash_16, small.dhash_16)
            elif scale > 0.25:
                dist = hamming(large.dhash_8, small.dhash_8)
            else:
                continue  # too small to hash reliably

            if dist > threshold:
                continue

            small_pixels = small.width * small.height
            corroboration = sum(1 for sig in CORROBORATING_SIGNALS if sig(small, large))

            if small_pixels < SMALL_IMAGE_PIXELS:
                if corroboration < 2:
                    continue  # skip — insufficient evidence for small image
                confidence = min(1 - dist / len(hash_a), 0.65)  # hard ceiling
                verify_carefully = True
                verify_reason = f"Small image ({small_pixels/1e6:.1f}MP) with {corroboration} corroborating signals"
            else:
                confidence = 1 - dist / len(hash_a)
                verify_carefully = False
                verify_reason = None

            yield CandidatePair(
                large.id, small.id, PREVIEW, confidence,
                verify_carefully=verify_carefully,
                verify_reason=verify_reason,
                meta={"scale": scale, "hamming": dist, "corroboration": corroboration}
            )
```

### L5 — Near Duplicate

```python
def detect_near_duplicates(images, threshold):
    bktree = BKTree(hamming_distance, [(img.id, img.dhash) for img in images])
    for img in images:
        for neighbor_id, dist in bktree.find(img.dhash, threshold['near_duplicate']):
            if neighbor_id > img.id:
                yield CandidatePair(
                    img.id, neighbor_id, NEAR_DUPLICATE,
                    confidence=1 - dist / 64,
                    meta={"hamming": dist}
                )
```

---

## Learning System

### Suppression

Every reviewed pair — confirmed OR rejected — is written to `suppression_pairs`. The detection pipeline loads the full suppression set at job start and skips any pair that appears in it. Previously reviewed pairs are never regenerated regardless of reprocess mode.

### Threshold Adaptation

Exponential moving average, updated after each decision on a layer with a tunable threshold (L3, L4, L5):

```python
ALPHA = 0.15          # learning rate — ~15 decisions to shift threshold by 1 bit
LAYER_BOUNDS = {
    "format_variant":  (0, 4),
    "preview":         (1, 6),
    "near_duplicate":  (2, 12),
}

def update_threshold(catalog_id, layer, candidate, decision, session):
    if layer not in LAYER_BOUNDS:
        return

    t = load_threshold(catalog_id, layer, session)
    signal = candidate.detection_meta["hamming"]

    if decision == "confirmed_duplicate":
        target = signal + 1   # threshold can be at least this loose
    else:
        target = signal - 1   # threshold must be tighter than this

    lo, hi = LAYER_BOUNDS[layer]
    t.threshold = max(lo, min(hi, t.threshold * (1 - ALPHA) + target * ALPHA))
    t.confirmed_count += (decision == "confirmed_duplicate")
    t.rejected_count  += (decision == "not_duplicate")
    t.last_updated = utcnow()
```

### Reprocess Modes

```python
class ReprocessMode(Enum):
    NEW_IMAGES_ONLY   = "new"    # incremental — only images added since last run
    THRESHOLD_CHANGED = "layer"  # re-run specific layer whose threshold drifted ≥1 bit
    FULL_RESCAN       = "full"   # clear all unreviewed candidates, rerun all layers
```

`FULL_RESCAN` clears only `duplicate_candidates` where `reviewed_at IS NULL`. Decisions, suppression pairs, and archived images are never touched.

**Automatic reprocess trigger** (warehouse scheduler):
```python
def should_reprocess(catalog_id, session):
    for layer, t in load_thresholds(catalog_id, session).items():
        if abs(t.threshold - t.last_run_threshold) >= 1.0:
            return ReprocessMode.THRESHOLD_CHANGED, layer
    if count_images_since_last_run(catalog_id, session) > 0:
        return ReprocessMode.NEW_IMAGES_ONLY, None
    return None, None
```

---

## Job Integration

Three jobs in the existing `register_job` framework:

| Job type | Description | Mode |
|---|---|---|
| `hash_images_v2` | Compute `dhash_8/16/32` for images missing them | `ParallelJob` |
| `detect_duplicates_v2` | Run all 5 layers, insert candidates | Sequential |
| `reprocess_duplicates` | Re-run one layer after threshold drift | Sequential, parameterized |

**Warehouse pipeline after scan:**
```
scan complete
  → hash_images_v2        (new images only)
    → detect_duplicates_v2  (NEW_IMAGES_ONLY mode)

decision recorded
  → check threshold drift
    → reprocess_duplicates  (if any layer drifted ≥ 1 bit)
```

---

## API Surface

```
# Trigger detection
POST /api/jobs/submit
     {job_type: "detect_duplicates_v2", catalog_id, mode: "full|new|layer", layer?: str}

# Review queue
GET  /api/catalogs/{id}/duplicates/candidates
     ?layer=&min_confidence=&verify_carefully=&reviewed=false&limit=&offset=
GET  /api/catalogs/{id}/duplicates/candidates/{candidate_id}

# Decision (atomic: writes decision + suppression + archives if confirmed)
POST /api/catalogs/{id}/duplicates/candidates/{candidate_id}/decide
     {decision: "confirmed_duplicate|not_duplicate|deferred", primary_id?, notes?}

# Stats and learning state
GET  /api/catalogs/{id}/duplicates/stats
GET  /api/catalogs/{id}/duplicates/thresholds
PUT  /api/catalogs/{id}/duplicates/thresholds/{layer}
     {threshold: float}   -- manual override, resets confirmed/rejected counts

# Archive (read + restore only — no delete)
GET  /api/catalogs/{id}/archive
     ?reason=&archived_after=&limit=&offset=
POST /api/catalogs/{id}/archive/{archived_image_id}/restore
```

The `decide` endpoint is the core write path. It atomically:
1. Writes `duplicate_decisions` row
2. Writes `suppression_pairs` row
3. If `confirmed_duplicate`: copies image row to `archived_images`, sets image `status` to `archived`
4. Enqueues threshold update for the candidate's layer
5. Updates `candidate.reviewed_at`

---

## Implementation Order

1. **Schema migration** — add `dhash_16`, `dhash_32` to `images`; create four new tables
2. **`hash_images_v2` job** — extend hashing to compute 16- and 32-bit variants
3. **L1 + L2** — trivial SQL layers, validate candidate pipeline plumbing
4. **L3** — format variant grouping and confirmation
5. **`archived_images` + decide endpoint** — archive write path before any visual detection
6. **L4** — preview detection with corroboration and safety threshold
7. **L5 + BK-tree** — near-duplicate detection
8. **Learning loop** — threshold adaptation and reprocess trigger
9. **API + warehouse integration** — queue, stats, manual override endpoints
