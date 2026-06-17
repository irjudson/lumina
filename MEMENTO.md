# lumina

Lumina is a photo management and editing application that allows users to organize, edit, and export photos with advanced tools like highlights/shadows adjustments, multiple size presets, and bulk operations. It supports RAW file formats and provides both web-based UI for browsing and desktop-style editing workflows.

**Stack:** Python (FastAPI), PostgreSQL, Vue.js 3, TypeScript, Tailwind CSS

## Current Status
- Photo management application with full CRUD operations on images
- Supports RAW file formats including ARW and HEIC
- Has a web-based UI for browsing, editing, and exporting photos
- Features include highlights/shadows adjustments, multiple export size presets, and bulk exports

## Recent Decisions
- 2026-06-16: Added server-side image export functionality with ZIP support for selected images
- 2026-06-16: Implemented live preview of highlights/shadows in the editing UI using canvas rendering
- 2026-06-16: Introduced bulk export capability via a new endpoint and modal update to handle multiple image IDs

## Open Issues
- Download functionality requires server restart for Python route changes due to uvicorn PID 1 process supervision

## Key Files
- `/home/irjudson/Projects/lumina/backend/main.py`: Main FastAPI application entry point with routing including new export endpoints
- `/home/irjudson/Projects/lumina/backend/models/image.py`: Database model for image metadata and storage location tracking
- `/home/irjudson/Projects/lumina/frontend/src/components/ImageEditor.vue`: Vue component that renders the live preview of edited images with canvas-based highlights/shadows effect
- `/home/irjudson/Projects/lumina/backend/routers/export.py`: Router module defining endpoints for single and bulk image exports to JPEG/WebP/PNG formats
- `/home/irjudson/Projects/lumina/frontend/src/components/ExportModal.vue`: Vue modal component that handles user input for filename, format, quality, size preset during export process
- `/home/irjudson/Projects/lumina/backend/utils/image_processor.py`: Utility functions to perform image transformations including resizing and applying rotation/flips before export
- `/home/irjudson/Projects/lumina/frontend/src/views/Library.vue`: Main view showing the photo grid with selection capabilities, bulk action panel, and context menu options
- `/home/irjudson/Projects/lumina/backend/routers/image.py`: Router module handling image CRUD operations such as fetching metadata or updating edits like rotation and flip flags

## Recent Activity
- 2026-06-16: Added export-web route to backend for single images, implemented triggerDownload function with proper blob URL lifecycle management
- 2026-06-16: Integrated canvas-based live preview of highlights/shadows in ImageEditor.vue component using offscreen rendering technique
- 2026-06-16: Updated ExportModal to support multi-image mode and custom filename fields, added bulk export button in Library view
- 2026-06-16: Implemented server-side ZIP generation for multiple image exports with configurable prefix naming scheme
- 2026-06-16: Fixed download triggering logic by anchoring <a> element to DOM and deferring blob URL revocation
