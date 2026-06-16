# lumina

Lumina is a personal media cataloging and curation application that organizes images and videos, allowing users to tag, search, and browse their collections with AI-powered groupings.

**Stack:** Python (FastAPI), Vue.js, PostgreSQL, Docker

## Current Status
- Media cataloging backend supports image/video ingestion with thumbnail caching
- Frontend UI enables tagging, grouping, and browsing of media assets
- Merge functionality added for combining duplicate folk tags via a new API endpoint and UI modal

## Recent Decisions
- 2024-06-07: Added merge endpoint `/folk-tags/{id}/merge` to consolidate duplicate folk tags by re-pointing image references, updating ml_groups tag_id, then deleting the source tag
- 2024-06-07: Improved thumbnail serving logic to check cache before validating source path and added placeholder for unprocessable video files

## Open Issues
- Video thumbnails are not generated due to missing ffmpeg integration
- Some media entries may have broken links if original sources were deleted or moved

## Key Files
- `/home/irjudson/Projects/lumina/api/main.py`: Main FastAPI application entry point with routes for catalogs, images, and folk tags including new merge functionality
- `/home/irjudson/Projects/lumina/api/routes/folk_tags.py`: Route definitions handling CRUD operations on folk tags, including the new POST /merge endpoint
- `/home/irjudson/Projects/lumina/frontend/src/views/CurateView.vue`: Main curation view displaying media grid and right panel for tag details with merge button UI
- `/home/irjudson/Projects/lumina/api/models.py`: Database models defining structures like Catalog, Image, FolkTag, MLGroup used throughout the app
- `/home/irjudson/Projects/lumina/frontend/src/store/index.js`: Vuex store managing application state including folk tag data and UI interactions for merge flow
- `/home/irjudson/Projects/lumina/api/routes/images.py`: Image handling endpoints, including thumbnail generation and serving logic improved to prioritize cache lookups
- `/home/irjudson/Projects/lumina/frontend/src/components/FolkTagDetailPanel.vue`: Component rendering tag details in the right panel with buttons for delete and merge actions
- `/home/irjudson/Projects/lumina/api/database.py`: Database connection setup using SQLAlchemy ORM to manage PostgreSQL schema and queries across models

## Recent Activity
- 2024-06-07: Implemented folk tag merging API endpoint and frontend modal with store integration for consolidating duplicate tags
- 2024-06-07: Fixed thumbnail serving logic to check cache before validating source path, preventing broken thumbnails on temporarily inaccessible files
- 2024-06-07: Added placeholder support in image thumbnail generation for video formats not supported by PIL
