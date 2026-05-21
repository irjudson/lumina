# lumina

Lumina is a personal media management system that organizes, tags, and catalogs photos and videos, offering smart search and discovery features through automated metadata extraction and AI-powered classification.

**Stack:** Python, FastAPI, PostgreSQL, Ollama, Docker, React

## Current Status
- Media library is actively being processed with automated tagging and classification
- Recent API endpoint had a bug causing 500 errors, now fixed
- VLM-based classification job is running in background to improve noise detection

## Recent Decisions
- 2024-05-20: Fixed ::timestamp cast syntax in SQL queries to resolve Recent API 500 errors
- 2024-05-20: Separated Screenshots, Documents, and Noise categories in classification for better organization
- 2024-05-20: Cancelled and restarted VLM classify job after fixing a critical bug in the API
- 2024-05-20: Improved heuristic-based classification to correctly label unclassified media
- 2024-05-20: Replaced outdated image processing logic with new batch handling for efficiency
- 2024-05-19: Implemented automatic tagging and organization of media based on metadata and AI

## Open Issues
- VLM classification job is still running and will take several hours to complete
- Some edge cases in file format detection may still cause misclassification

## Key Files
- `/home/irjudson/Projects/lumina/app/main.py`: Main FastAPI application entry point with routes and startup logic
- `/home/irjudson/Projects/lumina/app/database.py`: Database connection and ORM setup using SQLAlchemy
- `/home/irjudson/Projects/lumina/app/models.py`: Data models for media, tags, and classification
- `/home/irjudson/Projects/lumina/app/api/v1/endpoints/images.py`: API endpoints for image handling and metadata retrieval
- `/home/irjudson/Projects/lumina/app/services/classification.py`: Service layer for classifying media using heuristics and AI
- `/home/irjudson/Projects/lumina/app/services/tagging.py`: Service layer for automatic tagging based on content and metadata
- `/home/irjudson/Projects/lumina/app/core/config.py`: Configuration settings for the application environment and database
- `/home/irjudson/Projects/lumina/app/core/worker.py`: Background task runner for processing media and classification jobs

## Recent Activity
- 2024-05-20: Fixed ::timestamp syntax in SQL queries to resolve Recent API 500 errors
- 2024-05-20: Implemented new classification logic to better separate Screenshots, Documents, and Noise
- 2024-05-20: Cancelled and restarted VLM classify job after fixing a critical bug in the API
- 2024-05-20: Improved heuristic-based classification to correctly label unclassified media
- 2024-05-19: Added support for batch processing of media files with improved metadata extraction
- 2024-05-19: Integrated Ollama for advanced AI-powered classification of media content
- 2024-05-19: Refactored tagging logic to support automated and intelligent tag assignment
- 2024-05-18: Set up initial database schema and core data models for media management
- 2024-05-18: Configured FastAPI application with basic routing and startup hooks
- 2024-05-17: Initialized project structure and core dependencies for media processing pipeline
