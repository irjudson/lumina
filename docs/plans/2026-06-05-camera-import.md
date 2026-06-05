# Camera Import Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Lightroom-style camera/SD card import flow — detect mounted devices, browse new photos, copy to library with date-based structure, catalog them.

**Architecture:** Three new backend endpoints + one new job function wired into the existing job runner; eight new frontend files (store + components + view) plugged into the existing 3-panel layout. Reuses `_process_file_sequential` from `scanner.py` for cataloging and `_make_date_dir`/`_make_filename` from `organize.py` for destination paths.

**Tech Stack:** FastAPI, SQLAlchemy, PIL, shutil (backend); Vue 3, Pinia, TailwindCSS, lucide-vue-next (frontend).

---

## Task 1: Add `camera_import` job function

**Files:**
- Create: `lumina/jobs/definitions/camera_import.py`
- Modify: `lumina/jobs/job_implementations.py` (add to `JOB_FUNCTIONS`)
- Modify: `lumina/jobs/definitions/__init__.py` (import to register)
- Test: `tests/jobs/test_camera_import_job.py`

### Step 1: Write the failing test

```python
# tests/jobs/test_camera_import_job.py
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from PIL import Image as PILImage

from lumina.db.models import Catalog, Image
from lumina.jobs.definitions.camera_import import camera_import_job
from lumina.jobs.types import JobContext


pytestmark = pytest.mark.integration


@pytest.fixture
def catalog_with_output(db_session, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    catalog_id = uuid.uuid4()
    catalog = Catalog(
        id=catalog_id,
        name="Test",
        schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
        source_directories=[str(tmp_path / "src")],
        organized_directory=str(output_dir),
    )
    db_session.add(catalog)
    db_session.commit()
    return catalog, output_dir


@pytest.fixture
def source_image(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    img_path = src / "IMG_001.jpg"
    PILImage.new("RGB", (100, 100), color=(128, 0, 0)).save(str(img_path))
    return img_path


def test_camera_import_copies_and_catalogs(catalog_with_output, source_image, db_session):
    catalog, output_dir = catalog_with_output

    ctx = JobContext(
        job_id=str(uuid.uuid4()),
        catalog_id=str(catalog.id),
        parameters={
            "file_paths": [str(source_image)],
            "delete_source": False,
        },
    )

    result = camera_import_job(ctx)

    assert result["copied"] == 1
    assert result["cataloged"] == 1
    assert result["failed"] == 0
    # Source still exists (delete_source=False)
    assert source_image.exists()
    # At least one file in output_dir
    copied = list(output_dir.rglob("*.jpg"))
    assert len(copied) == 1


def test_camera_import_delete_source(catalog_with_output, source_image, db_session):
    catalog, output_dir = catalog_with_output

    ctx = JobContext(
        job_id=str(uuid.uuid4()),
        catalog_id=str(catalog.id),
        parameters={
            "file_paths": [str(source_image)],
            "delete_source": True,
        },
    )

    camera_import_job(ctx)

    assert not source_image.exists()


def test_camera_import_no_organized_directory(db_session, tmp_path):
    catalog_id = uuid.uuid4()
    catalog = Catalog(
        id=catalog_id,
        name="No Output",
        schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
        source_directories=[str(tmp_path)],
        organized_directory=None,
    )
    db_session.add(catalog)
    db_session.commit()

    ctx = JobContext(
        job_id=str(uuid.uuid4()),
        catalog_id=str(catalog_id),
        parameters={"file_paths": [str(tmp_path / "x.jpg")], "delete_source": False},
    )

    result = camera_import_job(ctx)
    assert result["error"] == "no_organized_directory"
```

### Step 2: Run test to verify it fails

```bash
cd /home/irjudson/Projects/lumina
source venv/bin/activate
pytest tests/jobs/test_camera_import_job.py -v
```
Expected: `ImportError` — `camera_import` module doesn't exist yet.

### Step 3: Write the implementation

```python
# lumina/jobs/definitions/camera_import.py
"""Camera import job — copies device files to organized_directory then catalogs them."""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..background_jobs import should_stop_job, update_job_status
from ..types import JobContext

logger = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".webm"}


def _get_capture_time(source_path: Path):
    """Return EXIF capture time or mtime fallback."""
    try:
        from lumina.analysis.metadata import MetadataExtractor
        from lumina.core.types import FileType

        ft = FileType.VIDEO if source_path.suffix.lower() in VIDEO_SUFFIXES else FileType.IMAGE
        with MetadataExtractor() as extractor:
            meta = extractor.extract_metadata(source_path, ft)
            dates = extractor.extract_dates(source_path, meta)
            if dates and dates.capture_time:
                return dates.capture_time
    except Exception:
        pass
    return datetime.fromtimestamp(source_path.stat().st_mtime)


def _dest_path(output_dir: Path, source_path: Path, capture_time) -> Path:
    """Build YYYY/MM-DD/YYYYMMDD_HHMMSS.ext destination path."""
    from lumina.jobs.definitions.organize import _make_date_dir, _make_filename

    date_dir = _make_date_dir(capture_time)
    filename = _make_filename(capture_time, source_path.suffix.lower())
    dest = output_dir / date_dir / filename

    # Collision resolution: append _1, _2, ...
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists():
            dest = dest.parent / f"{stem}_{counter}{suffix}"
            counter += 1
    return dest


def camera_import_job(ctx: JobContext) -> Dict[str, Any]:
    """Copy device files into organized_directory then catalog each one."""
    file_paths = ctx.parameters.get("file_paths", [])
    delete_source = ctx.parameters.get("delete_source", False)

    # Resolve catalog
    from lumina.db import get_db_context
    from lumina.db.models import Catalog

    with get_db_context() as db:
        catalog = db.query(Catalog).filter(Catalog.id == ctx.catalog_id).first()
        if not catalog:
            return {"error": "catalog_not_found"}
        if not catalog.organized_directory:
            return {"error": "no_organized_directory"}
        output_dir = Path(catalog.organized_directory)

    total = len(file_paths)
    copied = cataloged = failed = skipped = 0

    update_job_status(
        ctx.job_id, "PROGRESS",
        progress={"current": 0, "total": total, "percent": 0, "message": "Starting import..."},
    )

    from lumina.analysis.metadata import MetadataExtractor
    from lumina.analysis.scanner import _process_file_sequential
    from lumina.db import CatalogDB

    with MetadataExtractor() as extractor, CatalogDB(ctx.catalog_id) as catalog_db:
        for idx, file_path_str in enumerate(file_paths):
            if should_stop_job(ctx.job_id):
                break

            source = Path(file_path_str)
            if not source.exists():
                failed += 1
                continue

            try:
                capture_time = _get_capture_time(source)
                dest = _dest_path(output_dir, source, capture_time)
                dest.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(str(source), str(dest))
                copied += 1

                result = _process_file_sequential(dest, extractor)
                if result is not None:
                    image_record, _ = result
                    catalog_db.add_image(image_record)
                    cataloged += 1

                if delete_source and dest.exists():
                    source.unlink()

            except Exception as e:
                logger.error(f"Failed to import {file_path_str}: {e}")
                failed += 1

            percent = int((idx + 1) / total * 100) if total else 100
            update_job_status(
                ctx.job_id, "PROGRESS",
                progress={
                    "current": idx + 1,
                    "total": total,
                    "percent": percent,
                    "message": f"Imported {copied} of {total}...",
                    "rate": 0,
                },
            )

    return {
        "copied": copied,
        "cataloged": cataloged,
        "failed": failed,
        "skipped": skipped,
        "total": total,
    }
```

### Step 4: Register the job

Add to `lumina/jobs/job_implementations.py` — find the `JOB_FUNCTIONS` dict and add:

```python
from .definitions.camera_import import camera_import_job   # add near other imports

# Inside JOB_FUNCTIONS dict:
"camera_import": camera_import_job,
```

Add to `lumina/jobs/definitions/__init__.py`:
```python
from . import bursts, camera_import, detect_duplicates_v2, duplicates, hash_v2, scan

__all__ = ["bursts", "camera_import", "detect_duplicates_v2", "duplicates", "hash_v2", "scan"]
```

### Step 5: Run tests to verify they pass

```bash
pytest tests/jobs/test_camera_import_job.py -v
```
Expected: all 3 tests PASS.

### Step 6: Commit

```bash
git add lumina/jobs/definitions/camera_import.py \
        lumina/jobs/definitions/__init__.py \
        lumina/jobs/job_implementations.py \
        tests/jobs/test_camera_import_job.py
git commit -m "feat: add camera_import job — copy device files to library and catalog"
```

---

## Task 2: Add `GET /catalogs/{id}/camera/devices` endpoint

**Files:**
- Modify: `lumina/api/routers/catalogs.py`
- Test: `tests/api/test_camera_import_api.py`

### Step 1: Write the failing test

```python
# tests/api/test_camera_import_api.py
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from lumina.db.models import Catalog

pytestmark = pytest.mark.integration


@pytest.fixture
def catalog(db_session):
    catalog_id = uuid.uuid4()
    c = Catalog(
        id=catalog_id,
        name="Cam Test",
        schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
        source_directories=["/tmp"],
        organized_directory="/tmp/output",
    )
    db_session.add(c)
    db_session.commit()
    return c


def test_devices_returns_empty_when_no_mounts(client, catalog):
    with patch("pathlib.Path.exists", return_value=False):
        response = client.get(f"/api/catalogs/{catalog.id}/camera/devices")
    assert response.status_code == 200
    assert response.json() == []


def test_devices_returns_dcim_device(client, catalog, tmp_path):
    device_dir = tmp_path / "EOS_DIGITAL"
    dcim_dir = device_dir / "DCIM"
    dcim_dir.mkdir(parents=True)
    # Put one jpg in DCIM
    (dcim_dir / "IMG_001.JPG").write_bytes(b"fake")

    with patch(
        "lumina.api.routers.catalogs.DEVICE_MOUNT_ROOTS",
        [tmp_path],
    ):
        response = client.get(f"/api/catalogs/{catalog.id}/camera/devices")

    assert response.status_code == 200
    devices = response.json()
    assert len(devices) == 1
    assert devices[0]["name"] == "EOS_DIGITAL"
    assert devices[0]["file_count_estimate"] == 1
```

### Step 2: Run test to verify it fails

```bash
pytest tests/api/test_camera_import_api.py::test_devices_returns_empty_when_no_mounts -v
```
Expected: FAIL — endpoint doesn't exist yet.

### Step 3: Add the endpoint to `lumina/api/routers/catalogs.py`

Add near the top of the file (after existing imports):
```python
from pathlib import Path as FilePath
```

Add near the bottom of the router, before or after `get_filter_options`:

```python
# ─── Camera import ────────────────────────────────────────────────────────────

DEVICE_MOUNT_ROOTS = [
    FilePath("/media"),
    FilePath("/run/media"),
    FilePath("/mnt"),
    FilePath("/Volumes"),  # macOS
]

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tiff", ".tif",
    ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2",
    ".mp4", ".mov", ".avi", ".mkv", ".m4v",
}


class DeviceInfo(BaseModel):
    name: str
    path: str
    dcim_path: str
    file_count_estimate: int


@router.get("/{catalog_id}/camera/devices", response_model=List[DeviceInfo])
def list_camera_devices(catalog_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return detected cameras/SD cards mounted on the system."""
    devices = []
    for mount_root in DEVICE_MOUNT_ROOTS:
        if not mount_root.exists():
            continue
        try:
            for device_dir in mount_root.iterdir():
                if not device_dir.is_dir():
                    continue
                dcim = device_dir / "DCIM"
                if not (dcim.exists() and dcim.is_dir()):
                    continue
                count = sum(
                    1 for f in dcim.rglob("*")
                    if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
                )
                devices.append(DeviceInfo(
                    name=device_dir.name,
                    path=str(device_dir),
                    dcim_path=str(dcim),
                    file_count_estimate=count,
                ))
        except PermissionError:
            continue
    return devices
```

Also add `BaseModel` to imports at top of file if not already present:
```python
from pydantic import BaseModel
```

### Step 4: Run tests to verify they pass

```bash
pytest tests/api/test_camera_import_api.py::test_devices_returns_empty_when_no_mounts \
       tests/api/test_camera_import_api.py::test_devices_returns_dcim_device -v
```
Expected: both PASS.

### Step 5: Commit

```bash
git add lumina/api/routers/catalogs.py tests/api/test_camera_import_api.py
git commit -m "feat: add GET /camera/devices endpoint for mounted camera detection"
```

---

## Task 3: Add `POST /catalogs/{id}/camera/discover` endpoint

**Files:**
- Modify: `lumina/api/routers/catalogs.py`
- Modify: `tests/api/test_camera_import_api.py`

### Step 1: Write the failing test

Add to `tests/api/test_camera_import_api.py`:

```python
from PIL import Image as PILImage


def test_discover_returns_new_files(client, catalog, tmp_path):
    # Create a real JPEG on disk
    img_path = tmp_path / "IMG_001.jpg"
    PILImage.new("RGB", (100, 100)).save(str(img_path))

    response = client.post(
        f"/api/catalogs/{catalog.id}/camera/discover",
        json={"device_path": str(tmp_path)},
    )
    assert response.status_code == 200
    files = response.json()
    assert len(files) == 1
    assert files[0]["filename"] == "IMG_001.jpg"
    assert files[0]["thumbnail_data_url"].startswith("data:image/jpeg;base64,")


def test_discover_skips_already_cataloged(client, catalog, db_session, tmp_path):
    from lumina.db.models import Image

    img_path = tmp_path / "IMG_002.jpg"
    PILImage.new("RGB", (100, 100)).save(str(img_path))

    # Pre-insert matching path in DB
    existing = Image(
        id=str(uuid.uuid4()),
        catalog_id=str(catalog.id),
        source_path=str(img_path),
        file_type="image",
        checksum="abc123",
        size_bytes=100,
        dates={},
        metadata_json={},
    )
    db_session.add(existing)
    db_session.commit()

    response = client.post(
        f"/api/catalogs/{catalog.id}/camera/discover",
        json={"device_path": str(tmp_path)},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_discover_no_organized_directory_returns_400(client, db_session, tmp_path):
    catalog_id = uuid.uuid4()
    c = Catalog(
        id=catalog_id,
        name="No Output",
        schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
        source_directories=["/tmp"],
        organized_directory=None,
    )
    db_session.add(c)
    db_session.commit()

    response = client.post(
        f"/api/catalogs/{catalog_id}/camera/discover",
        json={"device_path": str(tmp_path)},
    )
    assert response.status_code == 400
```

### Step 2: Run tests to verify they fail

```bash
pytest tests/api/test_camera_import_api.py -k "discover" -v
```
Expected: FAIL — endpoint doesn't exist yet.

### Step 3: Add the endpoint to `lumina/api/routers/catalogs.py`

Add these two models (after `DeviceInfo`):
```python
class DiscoverRequest(BaseModel):
    device_path: str


class DiscoveredFile(BaseModel):
    path: str
    filename: str
    size_bytes: int
    taken_at: Optional[str]  # ISO datetime or None
    thumbnail_data_url: str
```

Add the endpoint:
```python
@router.post("/{catalog_id}/camera/discover", response_model=List[DiscoveredFile])
def discover_camera_files(
    catalog_id: uuid.UUID,
    body: DiscoverRequest,
    db: Session = Depends(get_db),
):
    """Return new media files in device_path not yet in this catalog."""
    import base64
    import hashlib
    import io

    from PIL import Image as PILImage
    from sqlalchemy import text as sa_text

    catalog = db.query(Catalog).filter(
        Catalog.id == CAST(str(catalog_id), sa_UUID)
    ).first()
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found")
    if not catalog.organized_directory:
        raise HTTPException(
            status_code=400,
            detail="No destination directory configured — set one in Catalog Settings",
        )

    device_path = FilePath(body.device_path)
    if not device_path.exists():
        raise HTTPException(status_code=404, detail="Device path not found")

    # Collect all media files in device path
    candidates = [
        f for f in device_path.rglob("*")
        if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
    ]

    # Phase 1: fast path — filenames already in catalog source_path
    already_imported = set()
    for candidate in candidates:
        row = db.execute(
            sa_text(
                "SELECT 1 FROM images WHERE catalog_id = CAST(:cid AS uuid)"
                " AND source_path LIKE :pat LIMIT 1"
            ),
            {"cid": str(catalog_id), "pat": f"%/{candidate.name}"},
        ).first()
        if row:
            already_imported.add(str(candidate))

    # Phase 2: checksum check for unknowns
    unknowns = [c for c in candidates if str(c) not in already_imported]
    for candidate in unknowns:
        try:
            h = hashlib.sha256()
            with open(candidate, "rb") as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    h.update(chunk)
            checksum = h.hexdigest()
            row = db.execute(
                sa_text(
                    "SELECT 1 FROM images WHERE catalog_id = CAST(:cid AS uuid)"
                    " AND checksum = :cs LIMIT 1"
                ),
                {"cid": str(catalog_id), "cs": checksum},
            ).first()
            if row:
                already_imported.add(str(candidate))
        except Exception:
            pass  # keep as candidate if we can't read it

    new_files = [c for c in candidates if str(c) not in already_imported]

    results = []
    for f in new_files:
        # Generate small thumbnail
        try:
            with PILImage.open(str(f)) as img:
                img.thumbnail((200, 200))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=60)
                thumb = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            thumb = ""

        # Try to get taken_at from EXIF
        taken_at = None
        try:
            from lumina.analysis.metadata import MetadataExtractor
            from lumina.core.types import FileType

            ft = FileType.VIDEO if f.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".m4v"} else FileType.IMAGE
            with MetadataExtractor() as extractor:
                meta = extractor.extract_metadata(f, ft)
                dates = extractor.extract_dates(f, meta)
                if dates and dates.capture_time:
                    taken_at = dates.capture_time.isoformat()
        except Exception:
            pass

        results.append(DiscoveredFile(
            path=str(f),
            filename=f.name,
            size_bytes=f.stat().st_size,
            taken_at=taken_at,
            thumbnail_data_url=thumb,
        ))

    return results
```

You'll also need these imports at the top of `catalogs.py` (add if not present):
```python
from typing import List, Optional
from sqlalchemy.dialects.postgresql import UUID as sa_UUID
```

### Step 4: Run tests to verify they pass

```bash
pytest tests/api/test_camera_import_api.py -v
```
Expected: all tests PASS.

### Step 5: Commit

```bash
git add lumina/api/routers/catalogs.py tests/api/test_camera_import_api.py
git commit -m "feat: add POST /camera/discover endpoint — two-phase dedup, inline thumbnails"
```

---

## Task 4: Add camera API methods to frontend client

**Files:**
- Modify: `src/api/client.ts`

### Step 1: Add types and methods

Find the type definitions section and add:
```typescript
export interface CameraDevice {
  name: string
  path: string
  dcim_path: string
  file_count_estimate: number
}

export interface DiscoveredFile {
  path: string
  filename: string
  size_bytes: number
  taken_at: string | null
  thumbnail_data_url: string
}
```

Find the `LuminaApiClient` class and add these methods after `cancelJob`:
```typescript
async getCameraDevices(catalogId: string): Promise<CameraDevice[]> {
  const response = await this.client.get(`/catalogs/${catalogId}/camera/devices`)
  return response.data
}

async discoverCameraFiles(catalogId: string, devicePath: string): Promise<DiscoveredFile[]> {
  const response = await this.client.post(`/catalogs/${catalogId}/camera/discover`, {
    device_path: devicePath
  })
  return response.data
}
```

### Step 2: Verify TypeScript compiles

```bash
cd /home/irjudson/Projects/lumina
npm run type-check 2>/dev/null || npx tsc --noEmit
```
Expected: no errors.

### Step 3: Commit

```bash
git add src/api/client.ts
git commit -m "feat: add camera device and discover API client methods"
```

---

## Task 5: Create `cameraImport` Pinia store

**Files:**
- Create: `src/stores/cameraImport.ts`

### Step 1: Create the store

```typescript
// src/stores/cameraImport.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { CameraDevice, DiscoveredFile } from '@/api/client'
import type { Job } from '@/stores/jobs'
import { useCatalogStore } from '@/stores/catalog'

export interface SelectableFile extends DiscoveredFile {
  selected: boolean
}

export const useCameraImportStore = defineStore('cameraImport', () => {
  const catalogStore = useCatalogStore()

  const devices = ref<CameraDevice[]>([])
  const selectedDevice = ref<CameraDevice | null>(null)
  const discoveredFiles = ref<SelectableFile[]>([])
  const isDiscovering = ref(false)
  const discoverError = ref<string | null>(null)
  const deleteSource = ref(false)
  const currentJob = ref<Job | null>(null)

  const selectedFiles = computed(() => discoveredFiles.value.filter(f => f.selected))
  const totalSelectedBytes = computed(() =>
    selectedFiles.value.reduce((sum, f) => sum + f.size_bytes, 0)
  )

  async function fetchDevices() {
    if (!catalogStore.activeCatalog) return
    try {
      devices.value = await api.getCameraDevices(catalogStore.activeCatalog.id)
    } catch {
      devices.value = []
    }
  }

  async function discoverFiles(devicePath: string) {
    if (!catalogStore.activeCatalog) return
    isDiscovering.value = true
    discoverError.value = null
    discoveredFiles.value = []
    try {
      const files = await api.discoverCameraFiles(catalogStore.activeCatalog.id, devicePath)
      discoveredFiles.value = files.map(f => ({ ...f, selected: true }))
    } catch (e: any) {
      discoverError.value = e?.response?.data?.detail ?? 'Discovery failed'
    } finally {
      isDiscovering.value = false
    }
  }

  function toggleFile(path: string) {
    const f = discoveredFiles.value.find(f => f.path === path)
    if (f) f.selected = !f.selected
  }

  function selectAll() {
    discoveredFiles.value.forEach(f => { f.selected = true })
  }

  function deselectAll() {
    discoveredFiles.value.forEach(f => { f.selected = false })
  }

  async function startImport() {
    if (!catalogStore.activeCatalog) return
    const paths = selectedFiles.value.map(f => f.path)
    if (!paths.length) return
    const job = await api.createJob({
      catalog_id: catalogStore.activeCatalog.id,
      job_type: 'camera_import',
      params: {
        file_paths: paths,
        delete_source: deleteSource.value,
      },
    })
    currentJob.value = { ...job, created_at: job.created_at ?? new Date().toISOString() }
  }

  function reset() {
    discoveredFiles.value = []
    currentJob.value = null
    discoverError.value = null
    selectedDevice.value = null
  }

  return {
    devices,
    selectedDevice,
    discoveredFiles,
    isDiscovering,
    discoverError,
    deleteSource,
    currentJob,
    selectedFiles,
    totalSelectedBytes,
    fetchDevices,
    discoverFiles,
    toggleFile,
    selectAll,
    deselectAll,
    startImport,
    reset,
  }
})
```

### Step 2: Verify TypeScript compiles

```bash
npx tsc --noEmit
```
Expected: no errors.

### Step 3: Commit

```bash
git add src/stores/cameraImport.ts
git commit -m "feat: add cameraImport Pinia store"
```

---

## Task 6: Create `DeviceList.vue`

**Files:**
- Create: `src/components/camera/DeviceList.vue`

### Step 1: Create the component

```vue
<!-- src/components/camera/DeviceList.vue -->
<template>
  <div class="p-4 space-y-4">
    <div class="flex items-center justify-between">
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Devices</h4>
      <button @click="store.fetchDevices()" class="text-gray-500 hover:text-gray-300 transition-colors">
        <RefreshCwIcon class="w-3.5 h-3.5" />
      </button>
    </div>

    <div v-if="store.devices.length" class="space-y-2">
      <button
        v-for="device in store.devices"
        :key="device.path"
        @click="selectDevice(device)"
        class="w-full flex items-start gap-3 p-3 rounded-md text-left transition-colors"
        :class="store.selectedDevice?.path === device.path
          ? 'bg-blue-600/20 border border-blue-500/40'
          : 'bg-gray-800 hover:bg-gray-700 border border-transparent'"
      >
        <CameraIcon class="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />
        <div class="min-w-0">
          <div class="text-sm font-medium text-gray-200 truncate">{{ device.name }}</div>
          <div class="text-xs text-gray-500">{{ device.file_count_estimate }} files</div>
        </div>
      </button>
    </div>

    <div v-else class="text-xs text-gray-500 italic">No devices detected</div>

    <div class="pt-4 border-t border-gray-800">
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Manual Path</h4>
      <div class="flex gap-2">
        <input
          v-model="manualPath"
          placeholder="/path/to/DCIM"
          class="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
          @keydown.enter="selectManual"
        />
        <button
          @click="selectManual"
          :disabled="!manualPath"
          class="px-2 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs disabled:opacity-50"
        >
          Go
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { CameraIcon, RefreshCwIcon } from 'lucide-vue-next'
import { useCameraImportStore } from '@/stores/cameraImport'
import type { CameraDevice } from '@/api/client'

const store = useCameraImportStore()
const manualPath = ref('')
let pollTimer: number | null = null

function selectDevice(device: CameraDevice) {
  store.selectedDevice = device
  store.discoverFiles(device.dcim_path)
}

function selectManual() {
  if (!manualPath.value) return
  store.selectedDevice = { name: manualPath.value, path: manualPath.value, dcim_path: manualPath.value, file_count_estimate: 0 }
  store.discoverFiles(manualPath.value)
}

onMounted(() => {
  store.fetchDevices()
  pollTimer = window.setInterval(() => store.fetchDevices(), 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>
```

### Step 2: Verify TypeScript compiles

```bash
npx tsc --noEmit
```
Expected: no errors.

### Step 3: Commit

```bash
git add src/components/camera/DeviceList.vue
git commit -m "feat: add DeviceList component with 5s polling"
```

---

## Task 7: Create `ImportCard.vue`

**Files:**
- Create: `src/components/camera/ImportCard.vue`

### Step 1: Create the component

```vue
<!-- src/components/camera/ImportCard.vue -->
<template>
  <div
    class="relative group cursor-pointer rounded-md overflow-hidden border transition-all"
    :class="file.selected ? 'border-blue-500' : 'border-gray-700 opacity-60'"
    @click="$emit('toggle', file.path)"
  >
    <!-- Thumbnail -->
    <div class="aspect-square bg-gray-800">
      <img
        v-if="file.thumbnail_data_url"
        :src="file.thumbnail_data_url"
        :alt="file.filename"
        class="w-full h-full object-cover"
      />
      <div v-else class="w-full h-full flex items-center justify-center">
        <ImageIcon class="w-8 h-8 text-gray-600" />
      </div>
    </div>

    <!-- Checkbox overlay -->
    <div class="absolute top-1.5 left-1.5">
      <div
        class="w-5 h-5 rounded border-2 flex items-center justify-center transition-colors"
        :class="file.selected
          ? 'bg-blue-500 border-blue-500'
          : 'bg-black/40 border-gray-400'"
      >
        <CheckIcon v-if="file.selected" class="w-3 h-3 text-white" />
      </div>
    </div>

    <!-- Filename tooltip on hover -->
    <div class="absolute bottom-0 inset-x-0 bg-black/70 px-1.5 py-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <div class="text-xs text-gray-200 truncate">{{ file.filename }}</div>
      <div v-if="file.taken_at" class="text-xs text-gray-400">{{ formatDate(file.taken_at) }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ImageIcon, CheckIcon } from 'lucide-vue-next'
import type { SelectableFile } from '@/stores/cameraImport'

defineProps<{ file: SelectableFile }>()
defineEmits<{ (e: 'toggle', path: string): void }>()

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}
</script>
```

### Step 2: Commit

```bash
git add src/components/camera/ImportCard.vue
git commit -m "feat: add ImportCard component with checkbox overlay"
```

---

## Task 8: Create `ImportGrid.vue`

**Files:**
- Create: `src/components/camera/ImportGrid.vue`

### Step 1: Create the component

```vue
<!-- src/components/camera/ImportGrid.vue -->
<template>
  <div class="flex flex-col h-full">
    <!-- Toolbar -->
    <div class="flex items-center gap-3 px-4 py-3 border-b border-gray-800 shrink-0">
      <button @click="store.selectAll()" class="text-xs text-blue-400 hover:text-blue-300">Select All</button>
      <span class="text-gray-700">|</span>
      <button @click="store.deselectAll()" class="text-xs text-blue-400 hover:text-blue-300">None</button>
      <span class="text-xs text-gray-500 ml-auto">
        {{ store.selectedFiles.length }} / {{ store.discoveredFiles.length }} selected
      </span>
      <button
        v-if="store.selectedDevice"
        @click="store.discoverFiles(store.selectedDevice!.dcim_path)"
        :disabled="store.isDiscovering"
        class="flex items-center gap-1.5 px-3 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded text-xs disabled:opacity-50"
      >
        <RefreshCwIcon class="w-3 h-3" :class="store.isDiscovering ? 'animate-spin' : ''" />
        Refresh
      </button>
    </div>

    <!-- States -->
    <div class="flex-1 overflow-y-auto p-4">
      <!-- No device selected -->
      <div v-if="!store.selectedDevice" class="flex flex-col items-center justify-center h-full text-center">
        <CameraIcon class="w-12 h-12 text-gray-700 mb-4" />
        <p class="text-sm text-gray-400">Select a device from the left panel</p>
      </div>

      <!-- Discovering -->
      <div v-else-if="store.isDiscovering" class="flex flex-col items-center justify-center h-full">
        <LoaderIcon class="w-8 h-8 text-blue-500 animate-spin mb-3" />
        <p class="text-sm text-gray-400">Scanning for new photos...</p>
      </div>

      <!-- Error -->
      <div v-else-if="store.discoverError" class="flex flex-col items-center justify-center h-full text-center">
        <AlertCircleIcon class="w-10 h-10 text-red-500 mb-3" />
        <p class="text-sm text-red-400">{{ store.discoverError }}</p>
      </div>

      <!-- No new files -->
      <div v-else-if="store.discoveredFiles.length === 0 && store.selectedDevice" class="flex flex-col items-center justify-center h-full text-center">
        <CheckCircleIcon class="w-12 h-12 text-green-600 mb-4" />
        <p class="text-sm text-gray-400">All photos already imported</p>
      </div>

      <!-- Grid -->
      <div v-else class="grid gap-2" style="grid-template-columns: repeat(auto-fill, minmax(120px, 1fr))">
        <ImportCard
          v-for="file in store.discoveredFiles"
          :key="file.path"
          :file="file"
          @toggle="store.toggleFile"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { CameraIcon, LoaderIcon, AlertCircleIcon, CheckCircleIcon, RefreshCwIcon } from 'lucide-vue-next'
import { useCameraImportStore } from '@/stores/cameraImport'
import ImportCard from './ImportCard.vue'

const store = useCameraImportStore()
</script>
```

### Step 2: Commit

```bash
git add src/components/camera/ImportGrid.vue
git commit -m "feat: add ImportGrid component with Lightroom-style selection"
```

---

## Task 9: Create `ImportOptions.vue`

**Files:**
- Create: `src/components/camera/ImportOptions.vue`

### Step 1: Create the component

```vue
<!-- src/components/camera/ImportOptions.vue -->
<template>
  <div class="p-4 space-y-6">
    <div>
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Destination</h4>
      <div v-if="catalogStore.activeCatalog?.organized_directory" class="space-y-1">
        <div class="text-xs text-gray-500">Organized directory</div>
        <div class="text-xs text-gray-300 font-mono break-all">
          {{ catalogStore.activeCatalog.organized_directory }}/YYYY/MM-DD/
        </div>
      </div>
      <div v-else class="text-xs text-amber-400">
        No organized directory set. Configure one in Catalog Settings.
      </div>
    </div>

    <div class="pt-4 border-t border-gray-800">
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Options</h4>
      <label class="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          v-model="store.deleteSource"
          class="mt-0.5 rounded border-gray-700 bg-gray-800 text-red-600"
        />
        <div>
          <div class="text-xs text-gray-300">Delete from device after import</div>
          <div class="text-xs text-gray-500 mt-0.5">Frees space on camera/card</div>
        </div>
      </label>
    </div>

    <div class="pt-4 border-t border-gray-800">
      <h4 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Summary</h4>
      <div class="space-y-2 text-xs">
        <div class="flex justify-between">
          <span class="text-gray-400">Selected</span>
          <span class="text-gray-200">{{ store.selectedFiles.length }} files</span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-400">Total size</span>
          <span class="text-gray-200">{{ formatBytes(store.totalSelectedBytes) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useCameraImportStore } from '@/stores/cameraImport'
import { useCatalogStore } from '@/stores/catalog'

const store = useCameraImportStore()
const catalogStore = useCatalogStore()

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}
</script>
```

### Step 2: Commit

```bash
git add src/components/camera/ImportOptions.vue
git commit -m "feat: add ImportOptions component with delete-source toggle"
```

---

## Task 10: Create `CameraImportView.vue`

**Files:**
- Modify: `src/views/ImportView.vue` (replace placeholder content)

### Step 1: Replace the placeholder

Replace the entire contents of `src/views/ImportView.vue` with:

```vue
<template>
  <LibraryLayout>
    <PanelContainer
      :left-panel-visible="layoutStore.leftPanelVisible"
      :right-panel-visible="layoutStore.rightPanelVisible"
      :filmstrip-visible="false"
    >
      <!-- Left Panel: Devices -->
      <template #left>
        <LeftPanel :visible="layoutStore.leftPanelVisible" @toggle="layoutStore.toggleLeftPanel">
          <DeviceList />
        </LeftPanel>
      </template>

      <!-- Main Panel: Photo Grid or Job Progress -->
      <template #main>
        <div class="relative h-full flex flex-col">
          <PanelToggle position="left" :collapsed="!layoutStore.leftPanelVisible"
            @toggle="layoutStore.toggleLeftPanel" class="absolute top-2 left-2 z-20" />
          <PanelToggle position="right" :collapsed="!layoutStore.rightPanelVisible"
            @toggle="layoutStore.toggleRightPanel" class="absolute top-2 right-2 z-20" />

          <!-- Job progress -->
          <div v-if="store.currentJob" class="flex-1 flex items-center justify-center p-8">
            <div class="w-full max-w-md bg-gray-900 border border-gray-800 rounded-lg p-6">
              <div class="flex items-center gap-4 mb-4">
                <LoaderIcon v-if="isRunning" class="w-6 h-6 text-blue-500 animate-spin shrink-0" />
                <CheckCircleIcon v-else-if="isDone" class="w-6 h-6 text-green-500 shrink-0" />
                <AlertCircleIcon v-else class="w-6 h-6 text-red-500 shrink-0" />
                <div>
                  <div class="text-sm font-medium text-gray-200">
                    {{ isRunning ? 'Importing...' : isDone ? 'Import Complete' : 'Import Failed' }}
                  </div>
                  <div class="text-xs text-gray-500 mt-0.5">
                    {{ store.currentJob.progress?.message ?? '' }}
                  </div>
                </div>
              </div>
              <div v-if="isRunning" class="mb-4">
                <div class="flex justify-between text-xs text-gray-400 mb-1">
                  <span>{{ store.currentJob.progress?.current ?? 0 }} / {{ store.currentJob.progress?.total ?? 0 }}</span>
                  <span>{{ store.currentJob.progress?.percent ?? 0 }}%</span>
                </div>
                <div class="w-full bg-gray-800 rounded-full h-2">
                  <div class="bg-blue-600 h-2 rounded-full transition-all"
                    :style="{ width: `${store.currentJob.progress?.percent ?? 0}%` }" />
                </div>
              </div>
              <div v-if="isDone" class="flex gap-3">
                <router-link to="/"
                  class="flex-1 text-center px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-md">
                  View Library
                </router-link>
                <button @click="store.reset()"
                  class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded-md">
                  Import More
                </button>
              </div>
            </div>
          </div>

          <!-- Grid -->
          <ImportGrid v-else class="flex-1" />

          <!-- Bottom bar -->
          <div v-if="!store.currentJob && store.discoveredFiles.length > 0"
            class="shrink-0 flex items-center justify-between px-6 py-3 border-t border-gray-800 bg-gray-950">
            <span class="text-sm text-gray-400">
              {{ store.selectedFiles.length }} photo{{ store.selectedFiles.length !== 1 ? 's' : '' }} selected
            </span>
            <button
              @click="doImport"
              :disabled="store.selectedFiles.length === 0"
              class="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Import {{ store.selectedFiles.length > 0 ? store.selectedFiles.length : '' }} Photo{{ store.selectedFiles.length !== 1 ? 's' : '' }}
            </button>
          </div>
        </div>
      </template>

      <!-- Right Panel: Options -->
      <template #right>
        <RightPanel :visible="layoutStore.rightPanelVisible" @toggle="layoutStore.toggleRightPanel">
          <ImportOptions />
        </RightPanel>
      </template>

      <template #filmstrip><div /></template>
    </PanelContainer>
  </LibraryLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { LoaderIcon, CheckCircleIcon, AlertCircleIcon } from 'lucide-vue-next'
import LibraryLayout from '@/layouts/LibraryLayout.vue'
import PanelContainer from '@/components/layout/PanelContainer.vue'
import LeftPanel from '@/components/layout/LeftPanel.vue'
import RightPanel from '@/components/layout/RightPanel.vue'
import PanelToggle from '@/components/layout/PanelToggle.vue'
import DeviceList from '@/components/camera/DeviceList.vue'
import ImportGrid from '@/components/camera/ImportGrid.vue'
import ImportOptions from '@/components/camera/ImportOptions.vue'
import { useCameraImportStore } from '@/stores/cameraImport'
import { useLayoutStore } from '@/stores/layout'
import { api } from '@/api/client'

const store = useCameraImportStore()
const layoutStore = useLayoutStore()

const isRunning = computed(() =>
  store.currentJob?.status === 'running' || store.currentJob?.status === 'pending'
)
const isDone = computed(() => store.currentJob?.status === 'success')

let pollTimer: number | null = null

async function doImport() {
  await store.startImport()
  if (!store.currentJob) return
  pollTimer = window.setInterval(async () => {
    if (!store.currentJob) return
    try {
      const updated = await api.getJob(store.currentJob.id)
      store.currentJob = { ...updated, created_at: store.currentJob.created_at }
      if (updated.status === 'success' || updated.status === 'failure') {
        clearInterval(pollTimer!)
        pollTimer = null
      }
    } catch { /* ignore */ }
  }, 1500)
}

onMounted(() => layoutStore.setActiveModule('camera-import'))
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>
```

### Step 2: Verify TypeScript compiles

```bash
npx tsc --noEmit
```
Expected: no errors.

### Step 3: Commit

```bash
git add src/views/ImportView.vue
git commit -m "feat: replace ImportView placeholder with CameraImportView"
```

---

## Task 11: Update router and sidebar navigation

**Files:**
- Modify: `src/router/index.ts`
- Modify: `src/layouts/LibraryLayout.vue`

### Step 1: Add route to router

In `src/router/index.ts`, the `/import` route already points to `ImportModule`. Add the camera import route. Find the routes array and add:

```typescript
import CameraImportView from '@/views/ImportView.vue'  // already ImportView

// In routes array, after the /import route:
{
  path: '/import/camera',
  name: 'camera-import',
  component: () => import('@/views/ImportView.vue'),
},
```

Wait — `ImportView.vue` IS the camera view now. The current `/import` route uses `ImportModule`. So just add:

```typescript
// Add this import at the top:
import CameraImportView from '@/views/ImportView.vue'

// Add in routes array:
{
  path: '/import/camera',
  name: 'camera-import',
  component: CameraImportView,
},
```

### Step 2: Add Camera nav link to sidebar

In `src/layouts/LibraryLayout.vue`, find the Import nav link (around line 20) and add a Camera link after it:

```html
<router-link
  to="/import"
  class="px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200"
  :class="$route.path === '/import' ? 'bg-gray-700 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'"
>Import</router-link>
<router-link
  to="/import/camera"
  class="px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200"
  :class="$route.path.startsWith('/import/camera') ? 'bg-gray-700 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'"
>Camera</router-link>
```

Note: also update the existing Import link's `:class` to use `$route.path === '/import'` (exact match) so it doesn't also highlight when on `/import/camera`.

### Step 3: Verify TypeScript compiles

```bash
npx tsc --noEmit
```
Expected: no errors.

### Step 4: Commit

```bash
git add src/router/index.ts src/layouts/LibraryLayout.vue
git commit -m "feat: add /import/camera route and Camera nav entry"
```

---

## Task 12: Build frontend and commit static assets

### Step 1: Build

```bash
cd /home/irjudson/Projects/lumina
npm run build
```
Expected: successful build, output in `lumina/web/static/`.

### Step 2: Verify no build errors

Check for any TypeScript or Vue template errors in the build output.

### Step 3: Run the backend test suite to confirm no regressions

```bash
source venv/bin/activate
pytest tests/ -x -q --timeout=60
```
Expected: all tests pass.

### Step 4: Commit static assets

```bash
git add lumina/web/static/
git commit -m "feat: build camera import frontend"
```

---

## Summary

| Task | Files Changed | Test Coverage |
|---|---|---|
| 1: camera_import job | `lumina/jobs/definitions/camera_import.py`, `job_implementations.py`, `definitions/__init__.py` | `tests/jobs/test_camera_import_job.py` |
| 2: devices endpoint | `lumina/api/routers/catalogs.py` | `tests/api/test_camera_import_api.py` |
| 3: discover endpoint | `lumina/api/routers/catalogs.py` | `tests/api/test_camera_import_api.py` |
| 4: API client | `src/api/client.ts` | TypeScript compile check |
| 5: Pinia store | `src/stores/cameraImport.ts` | TypeScript compile check |
| 6: DeviceList | `src/components/camera/DeviceList.vue` | — |
| 7: ImportCard | `src/components/camera/ImportCard.vue` | — |
| 8: ImportGrid | `src/components/camera/ImportGrid.vue` | — |
| 9: ImportOptions | `src/components/camera/ImportOptions.vue` | — |
| 10: CameraImportView | `src/views/ImportView.vue` | — |
| 11: Router + nav | `src/router/index.ts`, `src/layouts/LibraryLayout.vue` | — |
| 12: Build + commit | `lumina/web/static/` | Full test suite |
