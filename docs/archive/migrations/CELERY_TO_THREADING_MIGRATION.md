# Celery to Threading Migration

**Completed:** February 2026
**Status:** Complete and deployed

## Overview

Migrated the job execution system from Celery-based task distribution to a ThreadPoolExecutor-based threading system. This eliminated external dependencies (Redis, Celery workers) while maintaining parallel processing capabilities and improving system simplicity.

## Motivation

- **Complexity:** Celery required Redis, worker processes, and complex coordination
- **Deployment:** Simplified Docker setup without broker/worker management
- **Dependencies:** Removed Celery and Redis from required dependencies
- **Maintenance:** Threading model easier to debug and monitor

## Changes Made

### Architecture

**Before (Celery):**
```
FastAPI → Celery Tasks → Redis Broker → Celery Workers → Database
```

**After (Threading):**
```
FastAPI → Background Jobs → ThreadPoolExecutor → Database
```

### Files Converted

All parallel job modules migrated from Celery decorators to plain functions with ThreadPoolExecutor:

1. `lumina/jobs/coordinator.py` - Core coordination with BatchManager
2. `lumina/jobs/parallel_scan.py` - File scanning (789 → 805 lines)
3. `lumina/jobs/parallel_thumbnails.py` - Thumbnail generation (412 → 458 lines)
4. `lumina/jobs/parallel_quality.py` - Quality scoring (401 → 417 lines)
5. `lumina/jobs/parallel_tagging.py` - AI tagging (523 → 571 lines)
6. `lumina/jobs/parallel_bursts.py` - Burst detection (660 → 633 lines)
7. `lumina/jobs/parallel_duplicates.py` - Duplicate detection (2278 → 2114 lines)
8. `lumina/jobs/job_implementations.py` - Connected to threading coordinators

### Code Patterns

**Celery Pattern (Before):**
```python
@app.task(bind=True, base=CoordinatorTask)
def coordinator_task(self: CoordinatorTask, catalog_id: str):
    job_id = self.request.id

    # Create worker tasks
    tasks = [worker_task.s(batch_id) for batch_id in batches]

    # Execute with chord
    chord(tasks)(finalizer_callback.s())
```

**Threading Pattern (After):**
```python
def coordinator(job_id: str, catalog_id: str):
    executor = get_executor()

    # Submit worker tasks
    futures = {}
    for batch_id in batches:
        future = executor.submit(worker, batch_id, ...)
        futures[future] = batch_id

    # Wait for completion
    results = []
    for future in as_completed(futures):
        results.append(future.result())

    # Run finalizer inline
    return finalizer(results, ...)
```

### Key Differences

| Aspect | Celery | Threading |
|--------|--------|-----------|
| Task ID | `self.request.id` | Passed as parameter |
| Workers | Separate processes | Thread pool |
| Coordination | chord/group | as_completed() |
| Callbacks | Async task chains | Inline function calls |
| Progress | publish_progress() | PostgreSQL-based tracking |
| Cancellation | revoke() | BatchManager.cancel() |

## Database Changes

### Job Tracking Tables

Added PostgreSQL tables for job coordination (previously handled by Celery):

- `job_batches` - Batch status and coordination
- `job_progress` - Real-time progress tracking
- `job_history` - Completed job records

### Progress Publishing

Replaced Celery's result backend with PostgreSQL-based progress:

```python
# Store progress in database
publish_job_progress(job_id, progress, message, phase)

# Retrieve via WebSocket or REST API
GET /api/jobs/{job_id}/progress
```

## Configuration Changes

### Removed

```bash
# No longer needed
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=...
```

### Added

```python
# Thread pool configuration
BACKGROUND_WORKERS=8  # Default thread pool size
```

## Deployment Impact

### Docker Compose (Before)

```yaml
services:
  redis:
    image: redis:7-alpine

  celery_worker:
    command: celery -A lumina.celery_app worker
    depends_on: [redis, postgres]

  api:
    depends_on: [redis, postgres]
```

### Docker Compose (After)

```yaml
services:
  api:
    depends_on: [postgres]
    # No redis or worker needed!
```

## Testing Updates

### Skipped Tests

Old Celery-specific tests were marked as skipped pending rewrite for threading:

- `tests/jobs/test_tasks.py` - 14 Celery task registration tests
- `tests/jobs/test_burst_tasks.py` - 5 Celery coordination tests

These tested internal Celery mechanics (task.name, chord callbacks, etc.) that no longer exist. Need integration tests for the threading workflow instead.

## Performance Impact

- **Throughput:** Similar to Celery (both use parallel processing)
- **Latency:** Slightly lower (no Redis roundtrip)
- **Memory:** Lower (threads vs processes)
- **Startup:** Faster (no worker pool initialization)

## Migration Commits

1. `0c16a96` - Convert coordinator.py to threading
2. `ae3411a` - Convert parallel_scan.py
3. `207926f` - Convert parallel_thumbnails.py
4. `5eaa7ae` - Convert parallel_quality.py
5. `12cb062` - Convert parallel_tagging.py
6. `b1c882f` - Convert parallel_bursts.py
7. `3bfb158` - Connect job_implementations
8. `e7f34c5` - Convert parallel_duplicates.py
9. `b684148` - Make Celery imports optional
10. `9cde8f9` - Skip Celery-specific burst tests
11. `5127174` - Skip Celery-specific task tests

## Lessons Learned

- Threading model is simpler for this use case (CPU-bound batch jobs)
- Direct database coordination more reliable than external broker
- Fewer moving parts = easier debugging and deployment
- Test suite needs to be rewritten for new architecture

## Future Work

- [ ] Write integration tests for threading workflows
- [ ] Add thread pool metrics to monitoring
- [ ] Document threading best practices
- [ ] Consider async/await for I/O-bound operations
