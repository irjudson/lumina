# Lumina - Session State

**Last Updated:** 2026-01-15 (Current Session)
**Branch:** main
**Session Focus:** Duplicate detection debugging - UI shows poor results

---

## Current Status

### ⚠️ DUPLICATE DETECTION NEEDS WORK

**Thumbnails:** ✅ Complete (98,932 / 98,932 - 100%)
**Duplicate Detection:** ⚠️ Completed but UI shows "terrible" results
**Current Configuration:** threshold=1, pixel verification 80%

**Statistics:**
- 5,472 duplicate groups created
- 45,646 images grouped (46% of collection)
- Avg group size: 8.6 images
- Group size distribution:
  - 2 images: 1,139 groups (21%)
  - 3-5 images: 1,333 groups (24%)
  - 6-10 images: 1,195 groups (22%)
  - 11-15 images: 649 groups (12%)
  - 16-20 images: 1,156 groups (21%)
  - >20 images: 0 groups (0%)

**Problem:** User checked UI and reported results are "terrible"
**Status:** Taking a break, will investigate specific UI issues when resuming

**Investigation Done So Far:**
- ✅ Verified thumbnails are working (98,928 files on disk)
- ✅ Checked group composition - different checksums but high pixel similarity
- ✅ Validated large groups contain legitimate duplicates (same photo, different metadata)
- ✅ Confirmed threshold=1 is deployed and working
- ✅ Pixel verification (80%) is filtering false positives (split 71 groups)
- ⚠️ Found 3,518 ungrouped images with pairs (likely due to MAX_GROUP_SIZE=20 limit)

**Next Steps When Resuming:**
1. Get specific examples of "terrible" groups from UI
2. Investigate why those specific groups are problematic
3. Determine if issue is with grouping algorithm, threshold, or pixel verification
4. Consider alternative approaches if current method is fundamentally flawed

---

## Problem Discovered (2026-01-10 Session)

### 🚨 Duplicate Detection Creating Massive False Positives

**Root Cause Analysis:**

1. **Too Permissive Hash Threshold**
   - Default: `similarity_threshold = 5` (Hamming distance)
   - **Impact:** Grouped completely unrelated images together

2. **Example False Positive Group:**
   - Seed image had **149 "duplicate" connections**
   - Included: paris.jpg, random iPhone photos from 2016-2020, Sony RAW files, HEIC files
   - All different subjects: food, cars, gym, architecture, birds
   - Hash distances: 2-4 (all below ≤5 threshold)
   - **Pixel similarity: 0.0%** (correctly identified as NOT duplicates)

3. **No Thumbnails Available**
   - 98,932 images, **0 thumbnails** in database
   - Pixel verification failed with `'NoneType' object has no attribute 'read'`
   - Pixel verification was disabled for diagnostics

**User Expectation:**
- "Many small groups (2-5 images)"
- "If I have any group > 20 I'd be surprised"
- Want same image in different formats/sizes/compression
- Don't want visually similar but different images

---

## Fixes Implemented

### 1. ✅ Tightened Hash Distance Threshold (≤5 → ≤1)

**Changes:**
```python
# File: lumina/jobs/parallel_duplicates.py

# Line 288 (coordinator default)
- similarity_threshold: int = 5,
+ similarity_threshold: int = 1,

# Line 1198 (finalizer default)
- similarity_threshold: int = 5,
+ similarity_threshold: int = 1,
```

**Impact:** Dramatically reduces false positives from perceptual hash matching

---

### 2. ✅ Converted Pixel Verification to Thumbnail-Only

**Before:** Attempted to read source files (failed on RAW formats)
**After:** Uses thumbnails exclusively

**Changes:**
```python
# File: lumina/jobs/parallel_duplicates.py

# Lines 56-111: compute_pixel_similarity()
def compute_pixel_similarity(
    img1_thumbnail: str,  # Changed from img1_path
    img2_thumbnail: str,  # Changed from img2_path
    thumbnail_size: int = 256
) -> float:
    # Load thumbnails (already JPEGs, fast to load)
    img1 = Image.open(img1_thumbnail).convert('RGB')
    img2 = Image.open(img2_thumbnail).convert('RGB')
    # ... MSE calculation ...

# Lines 142-171: verify_group_with_pixel_similarity()
# Updated to load thumbnail_path from database instead of source_path
```

**Benefits:**
- **Fast:** Small JPEGs vs large RAW files
- **Universal:** Works with all formats (ARW, HEIC, DNG, etc.)
- **Normalized:** Consistent size and quality for comparison

---

### 3. ✅ Re-enabled Pixel Verification (80% threshold)

**Changes:**
```python
# File: lumina/jobs/parallel_duplicates.py
# Lines 1267-1306: Phase 5 pixel verification

# Re-enabled with 80% similarity threshold for JPEG thumbnails
for idx, group in enumerate(groups):
    subgroups = verify_group_with_pixel_similarity(
        group, catalog_id, min_similarity=80.0, finalizer_id=finalizer_id
    )
```

**How it works:**
1. Perceptual hash finds candidate groups (fast, high recall)
2. Pixel verification filters false positives (slower, high precision)
3. MSE comparison on 256x256 thumbnails
4. Groups split when pixel similarity < 80%
5. Union-Find regroupsverified duplicates

**Threshold rationale:**
- 95% too strict for JPEG thumbnails (compression artifacts)
- 85% still rejected ALL groups in testing
- 80% balances compression tolerance with false positive filtering

---

### 4. ✅ Rebuilt Containers

**Timestamp:** 2026-01-10 23:21 UTC
**Status:** All changes deployed and active

---

## Thumbnail Generation Progress

### Job Configuration
- **Catalog:** `bd40ca52-c3f7-4877-9c97-1c227389c8c4`
- **Coordinator Job:** `12a04400-d981-4c3f-8365-d73682974012`
- **Batches:** 99 × 1,000 images
- **Thumbnail size:** 256px
- **Quality:** 85 (JPEG)
- **Workers:** 12 active

### Current Status (23:32 UTC)
```
Thumbnails on disk: 9,974 / 98,932 (10%)
Database updates: 0 (finalizer will update when all batches complete)
Location: /app/catalogs/bd40ca52-c3f7-4877-9c97-1c227389c8c4/thumbnails/*_256.jpg
```

### Active Workers
```
celery@bbced8662072: 2 workers
celery@0f5e06c9d6ef: 2 workers
celery@d7220ce41b2e: 2 workers
celery@0a9e7be9ddbb: 2 workers
celery@2f4a6a671b95: 2 workers
celery@e0cca3b856bb: 2 workers
Total: 12 workers processing
```

**Note:** Workers survived container restart and continue processing.

---

## Next Steps (After Thumbnails Complete)

### 1. Clear Old Duplicate Data

```bash
PGPASSWORD=buffalo-jump psql -h localhost -U pg -d lumina -c "
DELETE FROM duplicate_pairs WHERE catalog_id = 'bd40ca52-c3f7-4877-9c97-1c227389c8c4';
DELETE FROM duplicate_groups WHERE catalog_id = 'bd40ca52-c3f7-4877-9c97-1c227389c8c4';
"
```

### 2. Re-run Duplicate Detection

```bash
docker compose exec cw python -c "
from lumina.jobs.parallel_duplicates import duplicates_coordinator_task

result = duplicates_coordinator_task.apply_async(
    kwargs={
        'catalog_id': 'bd40ca52-c3f7-4877-9c97-1c227389c8c4',
        'similarity_threshold': 1,  # New tighter threshold
        'recompute_hashes': False,
        'batch_size': 1000
    }
)
print(f'Duplicate detection dispatched: {result.id}')
"
```

### 3. Expected Results

**Before fix:**
- 1,517 groups with avg size 18.5
- Many groups of 20+ unrelated images
- Example: 149-connection mega-group

**After fix:**
- Tighter hash threshold (≤1 instead of ≤5) = fewer candidate groups
- Pixel verification at 80% = filters remaining false positives
- Expected: Many small groups (2-5 images)
- Groups contain truly duplicate images (same image, different formats/sizes)

---

## Monitoring Commands

### Thumbnail Progress
```bash
# Count generated thumbnails
docker compose exec cw bash -c "ls /app/catalogs/bd40ca52-c3f7-4877-9c97-1c227389c8c4/thumbnails/*_256.jpg 2>/dev/null | wc -l"

# Check database (0 until finalizer completes)
PGPASSWORD=buffalo-jump psql -h localhost -U pg -d lumina -c "
SELECT COUNT(*) as total, COUNT(thumbnail_path) as with_thumbs,
       ROUND(100.0 * COUNT(thumbnail_path) / NULLIF(COUNT(*), 0), 1) as pct
FROM images WHERE catalog_id = 'bd40ca52-c3f7-4877-9c97-1c227389c8c4'
"

# Check for finalizer completion
docker compose logs cw --tail=100 | grep "thumbnail_finalizer\|12a04400"
```

### Active Workers
```bash
docker compose exec cw celery -A lumina.jobs.celery_app inspect active | grep thumbnail_worker
```

---

## Files Modified (This Session)

**File:** `lumina/jobs/parallel_duplicates.py`

1. **Line 288:** Default `similarity_threshold: int = 5` → `1`
2. **Line 1198:** Finalizer default `similarity_threshold: int = 5` → `1`
3. **Lines 56-111:** Rewrote `compute_pixel_similarity()` for thumbnail-only comparison
4. **Lines 142-171:** Updated `verify_group_with_pixel_similarity()` to load thumbnail paths
5. **Lines 1267-1306:** Re-enabled pixel verification with 80% threshold

**Container Rebuild:** 2026-01-10 23:21 UTC ✅

---

## Key Learnings

### Perceptual Hash Limitations

**Hamming distance ≤5 is too permissive:**
- Creates groups of visually similar but semantically different images
- Example: Images with similar color palettes/composition grouped together
- Distance 2-4 was grouping completely unrelated subjects

**Optimal threshold:** ≤1 for true duplicates
- Distance 0: Exact hash match
- Distance 1: Minimal variation (same image, slight edit/crop/format)
- Distance 2+: Different images that happen to be visually similar

### Pixel Verification Approach

**MSE on thumbnails is ideal:**
- Fast: 256x256 JPEGs vs multi-MB RAW files
- Universal: Works with all formats
- Sufficient: Detects actual duplicates while filtering false positives
- Tolerant: 80% threshold handles JPEG compression variations

**Not ideal:**
- 95% threshold: Too strict for JPEG thumbnails
- Source file comparison: Too slow, fails on RAW formats
- Perceptual hash alone: Too many false positives

---

## Database State

**Catalog:** `bd40ca52-c3f7-4877-9c97-1c227389c8c4`
- **Images:** 98,932 total
- **Thumbnails:** 9,974 generated (10%)
- **Duplicate groups:** 1,517 (outdated, from ≤5 threshold)
- **Duplicate pairs:** 10,758,203 (outdated, to be cleared)

---

## Git Status

**Branch:** main
**Uncommitted changes:** `lumina/jobs/parallel_duplicates.py` (modifications not yet committed)

**Last commit:** `be28e78` - "docs: save session state - duplicate detector fix and rename completion"

---

## Quick Reference

### Check Thumbnail Count
```bash
ls /app/catalogs/bd40ca52-c3f7-4877-9c97-1c227389c8c4/thumbnails/*_256.jpg | wc -l
```

### Check Old Duplicate Data
```bash
PGPASSWORD=buffalo-jump psql -h localhost -U pg -d lumina -c "
SELECT
  (SELECT COUNT(*) FROM duplicate_groups WHERE catalog_id = 'bd40ca52-c3f7-4877-9c97-1c227389c8c4') as groups,
  (SELECT COUNT(*) FROM duplicate_pairs) as pairs;
"
```

### Analyze a Sample Group
```bash
docker compose exec cw python << 'EOFPYTHON'
from sqlalchemy import text
from lumina.db import CatalogDB as CatalogDatabase
from lumina.jobs.parallel_duplicates import compute_pixel_similarity
import os

catalog_id = "bd40ca52-c3f7-4877-9c97-1c227389c8c4"

with CatalogDatabase(catalog_id) as db:
    # Get a group seed
    result = db.session.execute(text("""
        SELECT image_1, COUNT(*) as connections
        FROM duplicate_pairs
        GROUP BY image_1
        HAVING COUNT(*) >= 19
        LIMIT 1
    """))

    row = result.fetchone()
    if row:
        print(f"Seed: {row[0][:16]}... with {row[1]} connections")
    else:
        print("No large groups found")
EOFPYTHON
```

---

## Previous Session Work (2026-01-04)

### Backend Fix - PostgreSQL Result Backend
- Fixed chord finalizer not firing (switched from `backend=None` to PostgreSQL)
- Cleaned up 45 GB of orphaned duplicate pairs
- All changes committed and pushed

### VAM Tools → Lumina Rename
- Complete rename across codebase and database
- All references updated
- Favicon and branding added

---

## Notes for Next Session

1. **Monitor thumbnail generation** - Check completion status
2. **When thumbnails complete:**
   - Clear old duplicate data
   - Re-run duplicate detection with new threshold
   - Verify results in UX
3. **Commit changes** - `lumina/jobs/parallel_duplicates.py` modifications
4. **Optional:** Implement quality-based duplicate resolution (design already complete)

---

## Technical Debt

1. Hanging pytest issue (88% in parallel mode)
2. Database collation warnings (cosmetic)
3. Untracked scripts in repo root
4. `analyze_group.py` script created for diagnostics (can remove)

---

## Session Metrics

**Session Start:** 2026-01-10 21:49 UTC
**Current Time:** 2026-01-10 23:32 UTC
**Duration:** ~1h 43m
**Token Usage:** ~110,000 / 200,000 (55%)
**Files Modified:** 1 (`lumina/jobs/parallel_duplicates.py`)
**Container Rebuilds:** 1
**Critical Bugs Fixed:** 1 (perceptual hash false positives)
**Jobs Dispatched:** 1 (thumbnail generation)
**Database Cleanup:** Pending (after thumbnail completion)
