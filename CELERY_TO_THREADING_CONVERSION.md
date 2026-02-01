# Celery to Threading Conversion Plan

## Overview
This document lists all parallel job functionality currently implemented with Celery that needs to be converted to the new threading-based job system.

## Completed
- ✅ Basic job submission and tracking (`background_jobs.py`, `job_implementations.py`)
- ✅ Job API endpoints (`jobs_new.py`)
- ✅ Test migration for core job functionality
- ✅ Removed dead code: `jobs.py` router, `jobs_stub.py`, `web/jobs_api.py`

## Files to Remove After Conversion
These files will be completely removed once parallel functionality is converted:
- `lumina/jobs/celery_app.py` - Celery application setup
- `lumina/jobs/config.py` - Celery configuration (Redis broker, etc.)
- `tests/jobs/test_celery_app.py` - Tests for Celery configuration

## Core Parallel Job Modules to Convert

### 1. Parallel Duplicate Detection
**File**: `lumina/jobs/parallel_duplicates.py` (84KB)
**Status**: ❌ Needs conversion
**Complexity**: High (uses Celery chord pattern extensively)

**Current Architecture**:
- Coordinator task spawns worker tasks via Celery chord
- Workers process batches of image pairs for similarity comparison
- Results aggregated by callback task
- Uses Celery-specific patterns: `.si()`, chord, group

**Key Functionality**:
- `duplicates_coordinator_task()` - Main coordinator
- `compute_duplicate_pairs_worker()` - Worker for pair comparison
- `aggregate_duplicate_results()` - Callback aggregator
- Batch planning with `DuplicateDetector.plan_batches()`
- Progress tracking via database job_batches table

**Threading Conversion Needs**:
- Replace Celery chord with ThreadPoolExecutor + futures
- Convert coordinator pattern to threading-based orchestration
- Maintain batch processing and progress tracking
- Keep database-based coordination (already in place)

**Dependencies**:
- Uses `coordinator.py` patterns (also needs conversion)
- Integrates with `DuplicateDetector` (analysis module - keep as-is)

---

### 2. Generic Parallel Job Coordinator
**File**: `lumina/jobs/coordinator.py` (28KB)
**Status**: ❌ Needs conversion
**Complexity**: High (core coordination pattern)

**Current Architecture**:
- Generic coordinator pattern used by all parallel jobs
- Spawns N worker tasks via Celery chord
- Monitors worker completion via database `job_batches` table
- Publishes aggregated progress updates

**Key Components**:
- `ParallelJobCoordinator` class - Main coordination logic
- `spawn_workers()` - Creates worker tasks via Celery
- `wait_for_workers()` - Monitors completion (database-based, thread-safe)
- `publish_aggregated_progress()` - Progress aggregation

**Threading Conversion Needs**:
- Replace Celery task spawning with ThreadPoolExecutor
- Keep database-based worker tracking (already thread-safe)
- Adapt progress aggregation for threading
- Maintain fault tolerance (worker failure handling)

**Used By**:
- All parallel_* modules (scan, thumbnails, quality, tagging, bursts)
- Critical infrastructure component

---

### 3. Parallel Scanning
**File**: `lumina/jobs/parallel_scan.py` (27KB)
**Status**: ❌ Needs conversion

**Current Architecture**:
- Coordinator + worker pattern for file scanning
- Workers process file batches in parallel
- Updates catalog database with discovered files

**Key Tasks**:
- `scan_coordinator_task()` - Spawns workers
- `scan_worker()` - Processes file batch
- Uses `ImageScanner` from analysis module

**Conversion Priority**: High (fundamental operation)

---

### 4. Parallel Thumbnail Generation
**File**: `lumina/jobs/parallel_thumbnails.py` (14KB)
**Status**: ❌ Needs conversion

**Current Architecture**:
- Coordinator spawns workers to generate thumbnails
- Each worker processes batch of images

**Key Tasks**:
- `thumbnails_coordinator_task()`
- `thumbnail_worker()`

**Conversion Priority**: Medium

---

### 5. Parallel Quality Scoring
**File**: `lumina/jobs/parallel_quality.py` (14KB)
**Status**: ❌ Needs conversion

**Current Architecture**:
- Coordinator + workers for image quality assessment
- Workers score image batches

**Key Tasks**:
- `quality_coordinator_task()`
- `quality_worker()`

**Conversion Priority**: Medium

---

### 6. Parallel Auto-Tagging
**File**: `lumina/jobs/parallel_tagging.py` (18KB)
**Status**: ❌ Needs conversion

**Current Architecture**:
- Coordinator + workers for AI-based image tagging
- Workers use OpenCLIP or Ollama models

**Key Tasks**:
- `tagging_coordinator_task()`
- `tagging_worker()`

**Conversion Priority**: Medium

---

### 7. Parallel Burst Detection
**File**: `lumina/jobs/parallel_bursts.py` (24KB)
**Status**: ❌ Needs conversion

**Current Architecture**:
- Coordinator + workers for burst detection
- Workers analyze image sequences

**Key Tasks**:
- `bursts_coordinator_task()`
- `burst_worker()`

**Conversion Priority**: Medium

---

### 8. Main Task Module
**File**: `lumina/jobs/tasks.py` (71KB)
**Status**: ⚠️ Partial conversion needed

**Current Architecture**:
- All Celery task definitions
- Entry points for job submission

**Key Tasks**:
- `analyze_catalog_task()` - Main analysis task
- `organize_catalog_task()` - File organization
- `generate_thumbnails_task()` - Thumbnail generation
- `detect_bursts_task()` - Burst detection
- `auto_tag_task()` - Auto-tagging
- And many more...

**Conversion Strategy**:
- Keep task function signatures for compatibility
- Replace Celery decorators with threading implementation
- Use new job_implementations.py pattern

**Conversion Priority**: High (entry point for all jobs)

---

## Supporting Modules

### 9. Job Recovery
**File**: `lumina/jobs/job_recovery.py` (14KB)
**Status**: ⚠️ Evaluate if needed

**Current Functionality**:
- Recovers stuck Celery jobs
- Monitors for stalled workers
- Celery-specific (uses task states)

**Threading Considerations**:
- Threading jobs don't need same recovery (fail-fast)
- May need different monitoring approach
- Could be simplified or removed

---

### 10. Progress Publisher
**File**: `lumina/jobs/progress_publisher.py` (11KB)
**Status**: ✅ Mostly compatible

**Current Functionality**:
- Publishes progress to SSE endpoints
- Database-based (not Celery-specific)

**Threading Compatibility**: Already thread-safe, minimal changes needed

---

### 11. Item Processors
**File**: `lumina/jobs/item_processors.py` (15KB)
**Status**: ✅ Compatible

**Current Functionality**:
- Pure processing functions (no Celery dependency)
- Used by workers to process individual items

**Threading Compatibility**: Already thread-safe

---

### 12. Job History
**File**: `lumina/jobs/job_history.py` (6KB)
**Status**: ✅ Compatible

**Current Functionality**:
- Database-based job tracking
- Replaced Redis tracking

**Threading Compatibility**: Already thread-safe

---

### 13. Memory Progress Manager
**File**: `lumina/jobs/memory_progress.py` (9KB)
**Status**: ✅ Compatible

**Current Functionality**:
- In-memory progress tracking
- Fallback when database unavailable

**Threading Compatibility**: Already thread-safe

---

## Parallel Job Utilities (Keep As-Is)

These modules don't use Celery and work with any parallel system:
- `lumina/jobs/duplicate_utils.py` - Duplicate detection utilities
- `lumina/jobs/scan_stats.py` - Scan statistics
- `lumina/jobs/job_metrics.py` - Performance metrics (already tested)
- `lumina/jobs/serial_descriptions.py` - Serial description generation

---

## Related Files to Update

### 14. File Reorganization
**File**: `lumina/jobs/reorganize.py` (20KB)
**Status**: ❌ Uses Celery tasks

**Current Implementation**:
- Calls Celery tasks for file operations
- Needs to use threading-based jobs

---

### 15. Health Check
**File**: `lumina/health_check.py**
**Status**: ⚠️ Has Celery import (commented out)

**Current State**:
- Already using database for health check
- Old Celery import commented out but should be removed

---

## Conversion Strategy

### Phase 1: Core Infrastructure (Week 1)
1. Convert `coordinator.py` to threading
2. Create threading-based worker spawn pattern
3. Establish ThreadPoolExecutor patterns

### Phase 2: Critical Operations (Week 2)
1. Convert `parallel_scan.py` (scanning is fundamental)
2. Convert `parallel_duplicates.py` (most complex, high value)
3. Update `tasks.py` entry points for converted modules

### Phase 3: Secondary Operations (Week 3)
1. Convert `parallel_thumbnails.py`
2. Convert `parallel_quality.py`
3. Convert `parallel_tagging.py`
4. Convert `parallel_bursts.py`

### Phase 4: Cleanup (Week 4)
1. Remove `celery_app.py`, `config.py`
2. Remove or simplify `job_recovery.py`
3. Update `reorganize.py`
4. Clean up test files
5. Remove Celery dependencies from pyproject.toml

---

## Testing Strategy

For each converted module:
1. Keep existing test structure (tests/jobs/test_*.py)
2. Replace Celery mocks with threading mocks
3. Verify parallel execution still works
4. Test worker failure scenarios
5. Validate progress tracking

---

## Key Design Patterns to Preserve

1. **Database-based coordination** - Already implemented, thread-safe
2. **Batch processing** - Keep current batch planning logic
3. **Progress tracking** - Maintain current progress API
4. **Fault tolerance** - Adapt for threading (fail-fast vs retry)
5. **Resource limiting** - Use ThreadPoolExecutor max_workers

---

## Dependencies to Remove (After Conversion)

From `pyproject.toml`:
```toml
# Celery and related (currently not in dependencies)
"celery>=5.0.0"
"redis>=4.0.0"  # Only needed for Celery broker
```

---

## Questions to Answer During Conversion

1. **Worker Failure Handling**:
   - Celery: Automatic retry and requeue
   - Threading: How to handle worker thread crashes?

2. **Resource Limits**:
   - Celery: Per-worker memory limits
   - Threading: How to prevent memory exhaustion?

3. **Long-Running Jobs**:
   - Celery: Task time limits
   - Threading: How to timeout stuck threads?

4. **Progress Granularity**:
   - Keep current batch-based progress?
   - Add per-item progress for UX?

5. **Concurrency Model**:
   - Use ThreadPoolExecutor (I/O bound)?
   - Use ProcessPoolExecutor (CPU bound)?
   - Hybrid approach?

---

## Success Criteria

- ✅ All parallel operations work without Celery
- ✅ Progress tracking maintains current accuracy
- ✅ No performance regression
- ✅ All tests pass
- ✅ Resource usage comparable or better
- ✅ Simpler deployment (no Redis, no Celery workers)
