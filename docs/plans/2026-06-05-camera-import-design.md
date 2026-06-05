# Camera Import Design

**Date:** 2026-06-05  
**Status:** Approved

## Overview

Add a Lightroom-style camera/SD card import flow to Lumina. When a device is connected, users can see new photos (not yet in the catalog), select which to import, and copy them into the library's organized directory structure. Files are never modified on the source device unless the user explicitly enables "delete after import."

## Decisions

| Question | Decision |
|---|---|
| What happens to source files? | Copy to library; optional delete-source toggle (off by default) |
| Destination structure | `organized_directory/YYYY/MM/filename` — matches existing organize job |
| New-file detection | Path basename match first (fast), SHA-256 checksum fallback for unknowns |
| Selection model | Lightroom-style: all new files checked by default, deselect to exclude |
| Device detection | Auto-detect known mount points + watchdog/inotify; manual path entry as fallback |
| Job architecture | Reuse existing `organize.py` copy logic and `scan.py` process_file; new `camera_import` job wires them together |

---

## Section 1: Navigation & Layout

- `/import` — unchanged, routes to `ImportModule.vue` (folder scan)
- `/import/camera` — new route, `CameraImportView.vue`
- Sidebar gains a second entry "Camera" alongside "Import"

**3-panel layout:**

- **Left panel** — Device list: auto-detected devices as clickable rows (device name + DCIM path), manual path input at bottom, live pulse indicator on new mount
- **Main panel** — Lightroom-style photo grid after device selected; checkbox overlay per card (all checked by default); toolbar with "Select All / None", count, and "Discover" button
- **Right panel** — Destination path preview, "Delete source after import" toggle (off by default), selected count and total size
- **Bottom bar** — "Import N Photos" button, disabled until at least one file selected

---

## Section 2: Backend API & Jobs

### `GET /catalogs/{id}/camera/devices`

Scans `/media`, `/run/media`, `/mnt`, `/Volumes` for directories with a `DCIM` subfolder.

Returns:
```json
[{ "name": "EOS_DIGITAL", "path": "/run/media/user/EOS_DIGITAL", "dcim_path": "/run/media/user/EOS_DIGITAL/DCIM", "file_count_estimate": 312 }]
```

### `POST /catalogs/{id}/camera/discover`

Body: `{ "device_path": "/run/media/user/EOS_DIGITAL" }`

Two-phase dedupe check:
1. Path basename match — `SELECT 1 FROM images WHERE source_path LIKE '%<filename>'`
2. For unknowns: compute SHA-256 and check `images.checksum`

Returns list of new files: `{ path, filename, size_bytes, taken_at, thumbnail_data_url }`. Thumbnail is a small base64 JPEG generated inline. Synchronous call; streams results in chunks of 200 for large cards.

Returns `400` if catalog has no `organized_directory` configured.

### `camera_import` job

New `JobType` entry and job definition. Parameters: `catalog_id`, `file_paths: list[str]`, `delete_source: bool`.

Steps (per file):
1. **Copy** — reuse `organize.py` copy-with-date-structure logic → `organized_directory/YYYY/MM/filename`
2. **Catalog** — reuse `scan.py` `process_file()` on the destination path
3. **Cleanup** — if `delete_source=True`, unlink source only after successful catalog

Progress reports per-file count. One bad file does not abort the batch.

---

## Section 3: Frontend Components & State

### New Pinia store: `src/stores/cameraImport.ts`

State: detected devices, selected device, discovered files (`{ ...file, selected: boolean }`), import options (`deleteSource: boolean`), current job ref.

Actions: `discoverFiles()`, `startImport()`, `toggleFile(path)`, `selectAll()`, `deselectAll()`.

### New components

| Component | Location | Role |
|---|---|---|
| `CameraImportView.vue` | `src/views/CameraImportView.vue` | Top-level view, composes 3-panel layout |
| `DeviceList.vue` | `src/components/camera/DeviceList.vue` | Left panel: device list + manual input |
| `ImportGrid.vue` | `src/components/camera/ImportGrid.vue` | Main panel: discovered file grid + toolbar |
| `ImportCard.vue` | `src/components/camera/ImportCard.vue` | Single file tile with checkbox overlay |
| `ImportOptions.vue` | `src/components/camera/ImportOptions.vue` | Right panel: destination + options |

### Routing

Add to `src/router/index.ts`:
```ts
{ path: '/import/camera', name: 'camera-import', component: CameraImportView }
```

Update `LibraryLayout.vue` sidebar to show both "Import" and "Camera" nav links.

### Device polling

`DeviceList.vue` polls `GET /camera/devices` every 5 seconds as fallback. Backend uses Python `watchdog` to watch mount points and push updates via the existing SSE stream for immediate notification.

---

## Section 4: Data Flow & Edge Cases

### Happy path

1. Open `/import/camera` → devices polled → left panel populated
2. Click device → `POST /camera/discover` → spinner → grid with all files checked
3. Deselect unwanted, configure options → "Import N Photos"
4. Job created → progress bar → poll via `api.getJob()`
5. Completion → summary ("312 imported, 4 skipped") + "View in Library" link

### Edge cases

| Scenario | Handling |
|---|---|
| Device disconnects mid-discover | Return error; UI shows "Device disconnected, please reconnect" |
| Device disconnects mid-import | Per-file failure; job continues; failed paths reported in result |
| Filename collision at destination | Append `_1`, `_2` suffix (same as organize job) |
| File already imported between discover and import | Checksum check in copy phase skips silently; reported as `skipped_already_exists` in result |
| Delete-source with copy failure | Source only deleted after destination confirmed written and cataloged |
| No `organized_directory` configured | `discover` returns 400: "No destination directory configured — set one in Catalog Settings" |
| Large cards (10k+ files) | Discover streams results in chunks of 200; grid renders incrementally |
