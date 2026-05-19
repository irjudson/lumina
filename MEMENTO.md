# lumina

Lumina is a modern image cataloging and analysis system that organizes photos through automated event detection, quality-based organization, and smart tagging. It provides a web interface for browsing, searching, and managing large photo collections with advanced deduplication and classification.

**Stack:** Python 3.11, PostgreSQL with pgvector, FastAPI, React, Docker, Celery, Redis

## Current Status
- Fully functional image cataloging system with automated event clustering and organization
- Supports tag-based browsing and filtering with sidebar interface
- Integrated with PostgreSQL for metadata storage and pgvector for similarity search
- Web UI provides full catalog browsing, map view, and event detection visualization
- Automated quality-based organization and deduplication pipeline across five layers
- Continuous integration with unit and integration tests

## Recent Decisions
- 2026-04-23: Merged feature/reorganize-v2 branch with event detection, auto-resolve, and tag browser features
- 2026-04-23: Updated documentation to reflect current architecture and feature set

## Open Issues
- No open issues

## Key Files
- `lumina/__main__.py`: Main entry point for the application
- `lumina/api/main.py`: FastAPI application with all routes and middleware
- `lumina/jobs/__init__.py`: Job orchestration and Celery integration
- `lumina/core/organization.py`: Core organization logic with quality rules and pick_primary
- `lumina/core/events.py`: Event detection and clustering algorithms
- `lumina/core/dedup.py`: Five-layer deduplication pipeline implementation
- `lumina/web/app.py`: React frontend application with UI components
- `lumina/web/components/EventsView.tsx`: UI component for displaying clustered events

## Recent Activity
- 2026-04-23: Merged feature/reorganize-v2 branch with event detection, auto-resolve, and tag browser features
- 2026-04-23: Updated documentation to reflect current architecture and feature set
- 2026-04-23: Added comprehensive unit and integration tests for new features
- 2026-04-23: Implemented quality-based organization rules and deduplication pipeline
- 2026-04-23: Added tag browser sidebar and primary tag display on hover
- 2026-04-23: Implemented haversine-based event clustering with union-find algorithm
- 2026-04-23: Added map view and thumbnail grid for event visualization
- 2026-04-23: Updated README, ARCHITECTURE.md, and USER_GUIDE.md documentation
- 2026-04-23: Fixed API error handling and test suite to pass CI checks
- 2026-04-23: Refactored core organization logic to support new quality rules
- 2026-04-23: Added event detection algorithm documentation and tests
- 2026-04-23: Integrated PostgreSQL with pgvector for similarity search
- 2026-04-23: Configured CI pipeline with unit and integration test matrix
- 2026-04-23: Implemented automated quality-based organization and deduplication
