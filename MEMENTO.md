# lumina

Lumina is a personal photo organization tool that automatically categorizes images into collections based on location, time, and other metadata, helping users browse and manage their photo library more effectively.

**Stack:** Python, FastAPI, React, PostgreSQL, Docker

## Current Status
- Travel collection algorithm has been improved to detect home bases and reduce micro-trips
- Collections can now be manually reordered with renamed ones prioritized
- Database schema updated to support user-renamed flags and manual sort positions

## Recent Decisions
- 2026-05-24: Improved travel trip detection by adding home base logic, raising min images/day, and loosening trip gaps to reduce micro-trips from 284 to 73
- 2026-05-24: Implemented manual collection reordering with renamed collections prioritized, and added user_renamed flag and sort_position fields to the database

## Open Issues
- Flight GPS artifacts in 2012 mid-Atlantic regions still geocode to ocean areas

## Key Files
- `lumina/models/collection.py`: Defines the collection model including new user_renamed and sort_position fields
- `lumina/api/collections.py`: API endpoints for collections including bulk reorder and auto-setting of user_renamed flag
- `lumina/services/travel_detector.py`: Logic for detecting travel collections with updated home base detection
- `lumina/store/collections.ts`: Frontend store logic for sorting collections by user_renamed flag and image count
- `lumina/components/NavigationSidebar.tsx`: Sidebar component that supports manual reordering of collections with drag handles
- `lumina/migrations/003_add_collection_sort_fields.py`: Database migration adding user_renamed and sort_position columns to collections
- `lumina/services/image_processor.py`: Service responsible for processing images and triggering collection categorization
- `lumina/api/auth.py`: Authentication middleware used for securing API endpoints

## Recent Activity
- 2026-05-24: Improved travel trip detection algorithm and re-ran categorization job
- 2026-05-24: Implemented manual collection reordering with renamed collections prioritized
- 2026-05-24: Updated database schema to support user-renamed flags and manual sort positions
- 2026-05-24: Modified collection sorting logic in frontend store and sidebar component
- 2026-05-24: Added bulk reorder endpoint and updated collection update logic in API
- 2026-05-24: Added user_renamed flag and sort_position fields to collection model and migration
- 2026-05-24: Re-ran categorize_images job with improved travel detection
- 2026-05-24: Added home base detection logic to travel categorization
