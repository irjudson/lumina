# lumina

Lumina is a web-based photo management application that allows users to organize, search, and view their photos. This project implements camera import functionality which enables importing photos from connected cameras via DCIM directories.

**Stack:** Vue.js 3 (Composition API), TypeScript, Pinia, Express.js, PostgreSQL

## Current Status
- Camera import feature is being implemented as per design document

## Recent Decisions
- 2026-06-05: Implemented camera device detection and discovery API endpoints for catalog imports

## Open Issues
- Need to implement file selection UI in frontend components

## Key Files
- `src/backend/api/catalogs.ts`: Handles all catalog-related routes including new camera import endpoints
- `src/backend/jobs/cameraImportJob.ts`: Defines the job logic for importing photos from connected cameras
- `src/frontend/views/CameraImportView.vue`: Main view component for selecting devices and managing imports
- `src/frontend/stores/cameraImportStore.ts`: Pinia store to manage state of camera import process including device list, selected files etc.
- `src/backend/types/index.ts`: Contains type definitions used across backend services
- `src/frontend/components/CameraDeviceList.vue`: Component listing available devices for photo import
- `src/frontend/components/CameraFileGrid.vue`: UI component to display and select individual photos from a device
- `docs/plans/2026-06-05-camera-import.md`: Design document outlining the implementation plan and requirements

## Recent Activity
- 2026-06-05: Created camera import API endpoints for discovering devices and files
- 2026-06-05: Defined backend job structure for importing photos from cameras
- 2026-06-05: Started implementing frontend components for device selection and file grid display
- 2026-06-05: Updated Pinia store to manage camera import state
- 2026-06-05: Set up routing configuration for the new camera import feature
