# Lumina Documentation

## Quick Start

- **[User Guide](guides/USER_GUIDE.md)** — Complete guide for end users
- **[Local Setup](guides/LOCAL_SETUP.md)** — Set up local development environment
- **[Docker Setup](guides/DOCKER_SETUP.md)** — Run with Docker

## Structure

```
docs/
├── guides/       # User and setup guides
├── technical/    # Architecture and implementation details
├── plans/        # Design documents (shipped features + active roadmap)
├── roadmap/      # Feature roadmap and improvement proposals
├── research/     # Investigations
├── findings/     # Analysis results
└── deployment/   # Deployment and configuration reference
```

## Guides

- **[User Guide](guides/USER_GUIDE.md)** — End-user documentation
- **[Quick Start](guides/QUICK_START.md)** — Get running fast
- **[Local Setup](guides/LOCAL_SETUP.md)** — Local development setup
- **[Docker Setup](guides/DOCKER_SETUP.md)** — Docker deployment
- **[Testing Guide](guides/TESTING.md)** — Running and writing tests
- **[GPU Setup](guides/GPU_SETUP_GUIDE.md)** — Enable GPU acceleration
- **[Job Safety](guides/JOB_SAFETY.md)** — Background job safety guidelines
- **[Troubleshooting](guides/TROUBLESHOOTING.md)** — Common problems and solutions
- **[Contributing](guides/CONTRIBUTING.md)** — How to contribute

## Technical

- **[Architecture](technical/ARCHITECTURE.md)** — System design and components
- **[How It Works](technical/HOW_IT_WORKS.md)** — Processing pipeline details
- **[Date Extraction](technical/DATE_EXTRACTION_GUIDE.md)** — Date detection algorithm
- **[Safety Guarantees](technical/SAFETY_GUARANTEES.md)** — Data safety architecture
- **[Development Approach](technical/DEVELOPMENT_APPROACH.md)** — Development methodology
- **[PostgreSQL Migration](technical/POSTGRES_MIGRATION.md)** — Database migration notes

## Plans (Shipped)

Design documents for completed features:

- **[V2 Architecture (2026-02-03)](plans/2026-02-03-v2-architecture.md)** — Threading job system, V2 refactor
- **[Deduplication Design (2026-04-13)](plans/2026-04-13-deduplication-design.md)** — 5-layer dedup system
- **[Deduplication Implementation (2026-04-13)](plans/2026-04-13-deduplication-implementation.md)**
- **[Camera Import Design (2026-06-05)](plans/2026-06-05-camera-import-design.md)** — Camera import with dedup
- **[Camera Import (2026-06-05)](plans/2026-06-05-camera-import.md)**
- **[Curation PRD (2026-06-07)](plans/2026-06-07-curation-prd.md)** — Folk tags, ML groups, curation UI
- **[Curation Architecture (2026-06-07)](plans/2026-06-07-curation-architecture-design.md)**
- **[Curation Implementation (2026-06-07)](plans/2026-06-07-curation-implementation.md)**

## Plans (Active Roadmap)

- **[Auto-Tagging Design](plans/AUTO_TAGGING_DESIGN.md)** — AI tagging system
- **[GPU Acceleration Plan](plans/GPU_ACCELERATION_PLAN.md)** — GPU implementation
- **[Catalog Browsing Optimization](plans/CATALOG_BROWSING_OPTIMIZATION_PLAN.md)** — UI performance

## Roadmap

- **[Roadmap](roadmap/ROADMAP.md)** — Feature priorities and future plans
- **[Composition Quality Scoring](roadmap/composition-quality-scoring.md)** — Future quality scoring
- **[Duplicate Detection Progress Aggregation](roadmap/improvements/duplicate-detection-progress-aggregation.md)**

## Research & Findings

- **[Video Perceptual Hashing](research/VIDEO_HASHING.md)** — Video hashing research
- **[Duplicate Detection Consensus (2025-12-30)](findings/2025-12-30-duplicate-detection-consensus-breakthrough.md)**

## Deployment

- **[Configuration](deployment/CONFIGURATION.md)** — Configuration reference
- **[Docker](deployment/DOCKER.md)** — Docker deployment details

---

**Main README**: [../README.md](../README.md) — Project overview and quick start
