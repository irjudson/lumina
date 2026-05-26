# lumina

Lumina is a personal media organization platform that automatically categorizes photos and videos into travel trips, work documents, and personal groups using AI and geolocation data. It helps users review and manage their media collections by suggesting meaningful groupings and allowing manual confirmation or correction of these assignments.

**Stack:** Python 3.12, FastAPI, PostgreSQL, React, Tailwind CSS, Docker

## Current Status
- The categorize job now correctly segments travel trips based on both time gaps and geographic jumps
- Family and archival decade sub-collections have been removed from the UI and database
- The "Ignore this person" sidebar action now clears and unassigns faces instead of permanently dismissing them
- Pending amber badges remain for all system-generated memberships, including travel trips

## Recent Decisions
- 2026-05-25: Changed 'Ignore this person' behavior to unassign faces instead of permanently dismissing them, allowing for re-clustering
- 2026-05-25: Removed decade-based sub-collections for Family & Personal and Archival categories
- 2026-05-25: Implemented dynamic trip segmentation that splits geographically distant trips even when time gaps are small

## Open Issues
- Pending badges still show for all system-generated memberships — consider auto-confirming travel and work trips
- Trip geo split logic may need further tuning for edge cases like very short flights

## Key Files
- `/home/irjudson/Projects/lumina/backend/categorize.py`: Main logic for grouping images into travel trips and other categories
- `/home/irjudson/Projects/lumina/backend/models.py`: Database models defining trips, memberships, and face clusters
- `/home/irjudson/Projects/lumina/backend/api.py`: API endpoints for managing memberships, clusters, and categorization
- `/home/irjudson/Projects/lumina/frontend/src/components/Sidebar.jsx`: Sidebar UI showing clusters and navigation items with pending counts
- `/home/irjudson/Projects/lumina/frontend/src/components/NavItem.jsx`: Navigation item component displaying counts and pending indicators
- `/home/irjudson/Projects/lumina/frontend/src/components/FaceCluster.jsx`: UI for displaying and managing face clusters in the sidebar
- `/home/irjudson/Projects/lumina/frontend/src/components/TravelTrip.jsx`: UI for displaying auto-generated travel trips and their pending memberships
- `/home/irjudson/Projects/lumina/backend/db_cleanup.py`: Script to remove stale decade sub-collections and clean up old trip data

## Recent Activity
- 2026-05-25: Implemented geographic trip splitting logic to prevent merging of distant locations
- 2026-05-25: Removed decade-based sub-collections from Family & Archival categories
- 2026-05-25: Updated sidebar action label from 'Ignore this person' to 'Clear & unassign faces'
- 2026-05-25: Fixed trip segmentation to use dynamic geographic jump detection
- 2026-05-25: Deployed changes to categorize job and frontend
- 2026-05-25: Committed all backend and frontend fixes to version control
- 2026-05-25: Updated database to remove stale family/archival sub-collections
- 2026-05-25: Configured pending badge behavior for system-generated memberships
- 2026-05-25: Ensured travel trips are segmented by both time and geographic distance
- 2026-05-25: Re-ran categorize job to apply new trip segmentation logic
