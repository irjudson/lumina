# Lumina Curation Architecture Design

## Vision

A 30-year personal archive of images captured for many purposes — family, work, travel,
art, history, documentation. The library grows continuously. The goal is not to finish
organizing it; the goal is to make it progressively more findable, one session at a time.

**Core principle: incremental enrichment.** Every curation session adds signal. The system
accumulates meaning over decades without ever requiring a complete pass.

**Findability target:** compound queries across any combination of dimensions —
*"photos of Mom at Yellowstone between 2010 and 2020"*,
*"family archive scans from before 1990"*,
*"Jake age 5–8 at any outdoor location"*.

---

## Guiding Constraints

- **All ML inference is local.** No external API calls during runtime processing.
  Ollama (shared-infra container, `http://ollama:11434`) is the inference gateway.
- **ML proposes, human decides.** The system never writes a confirmed annotation
  without explicit human review, unless a specific permission rule has been granted.
- **Permission grants are explicit and bounded.** "Auto-apply `type=scan` when
  confidence ≥ 0.95" is a rule the user sets consciously — not a global toggle.
- **The frontier model (Claude Code) is used only for calibration sessions,**
  user-triggered, not automatic. Over time, Memento replaces it entirely.
- **Source files are never modified.** The database is the source of truth.
  XMP export is a future layer.

---

## Annotation Dimensions

The following facets are the initial vocabulary. New facets can be added at any time
without schema migrations.

### Content Type
What kind of image is this?
- Photographic genres: `portrait`, `street`, `landscape`, `documentary`, `event`,
  `candid`, `macro`, `architectural`, `wildlife`, `abstract`, `aerial`
- Non-photographic: `document_scan`, `print_scan`, `screenshot`, `receipt`,
  `whiteboard`, `artwork_scan`, `film_scan`
- Functional: `test_shot`, `reference`, `burst_variant`

### Subject
What is the primary subject?
- `people`, `animal`, `object`, `place`, `nature`, `built_environment`, `text`, `food`,
  `vehicle`, `art`

### Who
Named individuals present. Structured — links to the `people` table.
- Name, relationship, birthdate (enables age-at-time queries)

### Where
- GPS-derived: country, region, city (already geocoded)
- Named personal places: "Grandma's house", "our cabin", "old office" (user-defined)
- Scene context: `indoor`, `outdoor`

### When
- EXIF timestamp (already stored)
- Life event: `graduation`, `wedding`, `birthday`, `holiday`, `milestone`,
  `first_day_of_school`, `anniversary`
- Recurring occasion: `christmas`, `thanksgiving`, `annual_trip`

### Purpose / Intent
Why was this taken / what is it for?
- `family_archive` — meant to be preserved and shared across generations
- `work_professional` — project documentation, conferences, whiteboards
- `travel_documentation` — places visited
- `artistic` — creative or experimental
- `historical_genealogical` — scans of old prints, family history
- `ephemeral` — screenshots, receipts, temp references
- `received` — not self-captured

### Quality / Status
- Pick status: `pick`, `reject`, `unreviewed`
- Technical: `sharp`, `blurry`, `well_exposed`, `underexposed`, `overexposed`
- Edit state: `raw_capture`, `edited`, `exported`

### Provenance
- `original_digital` — captured on a digital camera/phone
- `digitized_print` — scanned from a physical print
- `digitized_film` — scanned from film negative or slide
- `screenshot` — screen capture
- `downloaded_received` — from another person or source

---

## Data Model

### Core: Flexible Faceted Annotations

```sql
-- Dimensions
CREATE TABLE facets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        TEXT UNIQUE NOT NULL,         -- 'content_type', 'purpose', 'who'
    name        TEXT NOT NULL,
    data_type   TEXT NOT NULL,                -- 'term', 'person', 'place', 'event', 'range'
    is_multi    BOOLEAN DEFAULT TRUE,         -- can an image have multiple values?
    is_hier     BOOLEAN DEFAULT FALSE,        -- hierarchical (parent/child terms)?
    notes       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Values within a facet
CREATE TABLE terms (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facet_id    UUID NOT NULL REFERENCES facets(id),
    slug        TEXT NOT NULL,
    label       TEXT NOT NULL,
    synonyms    JSONB DEFAULT '[]',           -- alternate labels for matching
    parent_id   UUID REFERENCES terms(id),   -- for hierarchical facets
    UNIQUE (facet_id, slug)
);

-- Image ↔ Term: confirmed annotations
CREATE TABLE annotations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id        TEXT NOT NULL,            -- references images.id
    term_id         UUID NOT NULL REFERENCES terms(id),
    confidence      FLOAT DEFAULT 1.0,        -- 1.0 = human confirmed
    source          TEXT NOT NULL,            -- 'human', 'ml_confirmed', 'auto_rule'
    model           TEXT,                     -- which model suggested it (if ml)
    annotated_at    TIMESTAMPTZ DEFAULT NOW(),
    notes           TEXT,
    UNIQUE (image_id, term_id)
);
```

### Structured Companion Tables

```sql
-- Named people (face clusters get names here)
CREATE TABLE people (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_id      UUID NOT NULL,
    name            TEXT NOT NULL,
    birthdate       DATE,                     -- enables age-at-time queries
    relationship    TEXT,                     -- 'self', 'spouse', 'child', 'parent', etc.
    face_cluster_id TEXT,                     -- links to existing face cluster
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- image ↔ person join (richer than a term annotation)
CREATE TABLE image_people (
    image_id    TEXT NOT NULL,
    person_id   UUID NOT NULL REFERENCES people(id),
    confidence  FLOAT DEFAULT 1.0,
    source      TEXT NOT NULL,               -- 'human', 'face_recognition', 'ml_confirmed'
    PRIMARY KEY (image_id, person_id)
);

-- User-defined named places (beyond geocoding)
CREATE TABLE named_places (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_id  UUID NOT NULL,
    name        TEXT NOT NULL,               -- "Grandma's house", "our cabin"
    gps_lat     FLOAT,
    gps_lon     FLOAT,
    gps_radius  FLOAT,                       -- meters
    parent_id   UUID REFERENCES named_places(id),
    notes       TEXT
);

-- Named events / occasions
CREATE TABLE events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_id      UUID NOT NULL,
    name            TEXT NOT NULL,           -- "Jake's graduation 2023"
    event_type      TEXT,                    -- life_event term slug
    date_start      DATE,
    date_end        DATE,
    named_place_id  UUID REFERENCES named_places(id),
    gps_lat         FLOAT,
    gps_lon         FLOAT,
    gps_radius      FLOAT,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE image_events (
    image_id    TEXT NOT NULL,
    event_id    UUID NOT NULL REFERENCES events(id),
    confidence  FLOAT DEFAULT 1.0,
    source      TEXT NOT NULL,
    PRIMARY KEY (image_id, event_id)
);
```

### ML Suggestion Queue

```sql
-- ML proposals — never confirmed until human reviews
CREATE TABLE annotation_suggestions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id        TEXT NOT NULL,
    facet_id        UUID REFERENCES facets(id),
    term_id         UUID REFERENCES terms(id),    -- null if suggesting a new term
    suggested_value TEXT,                          -- for new terms not yet in vocabulary
    confidence      FLOAT NOT NULL,
    model           TEXT NOT NULL,                 -- 'qwen3-vl', 'clip', 'insightface'
    evidence        JSONB,                         -- model's reasoning / supporting data
    status          TEXT DEFAULT 'pending',        -- 'pending', 'confirmed', 'rejected', 'auto_applied'
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Rules that allow auto-apply without human review
CREATE TABLE auto_apply_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_id      UUID NOT NULL,
    facet_id        UUID REFERENCES facets(id),
    model           TEXT,                          -- null = any model
    min_confidence  FLOAT NOT NULL,
    granted_at      TIMESTAMPTZ DEFAULT NOW(),
    granted_by      TEXT DEFAULT 'user',
    notes           TEXT
);
```

### Model Performance Tracking

```sql
CREATE TABLE model_performance (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model           TEXT NOT NULL,
    facet_id        UUID REFERENCES facets(id),
    precision       FLOAT,
    recall          FLOAT,
    f1              FLOAT,
    sample_count    INT,
    evaluated_at    TIMESTAMPTZ DEFAULT NOW(),
    evaluated_by    TEXT NOT NULL             -- 'memento', 'frontier', 'human'
);

-- Learned routing: which model to use for which task on this library
CREATE TABLE routing_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task            TEXT NOT NULL,            -- 'classify_type', 'caption', 'detect_faces'
    image_context   JSONB,                    -- conditions: file_type, size, has_faces, etc.
    model           TEXT NOT NULL,
    priority        INT DEFAULT 0,
    source          TEXT NOT NULL,            -- 'memento', 'frontier', 'user'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

## ML Pipeline

All inference via Ollama at `http://ollama:11434`. Models already available:

| Model | Task |
|---|---|
| `qwen3-vl` | Image captioning, genre classification, content description, event boundary reasoning |
| `llava` | Fallback vision LLM |
| `qwen2.5:14b` | Text reasoning, batch analysis, routing decisions |
| `deepseek-r1` | Reasoning over complex grouping/classification tasks |
| `nomic-embed-text` | Text similarity for caption/tag matching |

Local models (run in Lumina's GPU-enabled container):
| Model | Task |
|---|---|
| CLIP ViT-L/14 | Zero-shot genre/subject classification, visual embeddings |
| InsightFace | Face detection, recognition, cluster linking to `people` |
| FAISS | Visual similarity search (already deployed) |
| Laplacian variance | Sharpness scoring (CPU, no model needed) |

### Processing Pipeline per Image

```
1. Ingest (already exists): EXIF → GPS → organized_path → FAISS embedding
2. Face pass: InsightFace → cluster → suggestion: who=<cluster_id>
3. Vision pass: qwen3-vl → caption + genre → suggestions: type=X, subject=Y
4. CLIP pass: zero-shot against facet vocabularies → suggestions with confidence
5. Quality pass: sharpness + histogram → suggestions: quality=sharp/blurry
6. All suggestions → annotation_suggestions (status=pending)
7. Human review session → confirm/reject → annotations table
```

---

## Curation Workflow

### Coverage Score

Every image gets a coverage score: fraction of "important" facets that have a confirmed
annotation. The default important facets are: `content_type`, `purpose`, `quality`.
As the user adds confirmed annotations, the definition of "important" can expand.

### Session Types

**Name the People** — highest leverage first pass
- Surface anonymous face clusters ordered by image count
- User names each cluster → `people` record created → all images in cluster get `who=X`
- System immediately suggests more images with similar faces

**Classify Image Types** — separates photos from scans from screenshots
- Surface images with no `content_type` annotation
- ML suggestions pre-filled; user confirms/corrects in batches of 50
- Once user confirms 20+ examples of a type, auto-apply rule can be enabled

**Label Events** — time + location clusters
- System groups images by GPS proximity + date proximity
- Presents each cluster: "34 images, 2019-08-14 to 2019-08-16, near Yellowstone NP"
- User names it, assigns event type → all images get the event annotation

**Review ML Suggestions** — ongoing
- Pending suggestions ordered by confidence (high first)
- Batch approve, batch reject, or correct individually
- Rejected suggestions feed back as negative training signal

**Find & Tag** — query-driven discovery
- User searches for images matching partial criteria
- From results, apply missing annotations in bulk
- "These 200 images from the 2018 family reunion have no purpose tag" → bulk apply

---

## Compound Search

Queries combine any facets with AND/OR logic:

```
person=Mom AND location=Yellowstone AND date=[2010,2020]
type=scan AND purpose=family_archive AND date=[*,1990]
person=Jake AND age=[5,10]              # resolved: birthdate + photo date
purpose=work_professional AND year=2023
type=portrait AND quality=pick AND who=untagged
```

Age queries: `Jake age 5–10` resolves to `person_id=Jake.id AND photo_date BETWEEN
(Jake.birthdate + 5yr) AND (Jake.birthdate + 10yr)`.

Similarity queries: "find images visually similar to this one" uses FAISS.

---

## Meta-Model Loop

### Now: Frontier Model (Claude Code, User-Triggered)

When the user wants a calibration session:
1. Pull recent suggestion confirmations and rejections from `annotation_suggestions`
2. Pull `model_performance` history
3. Frontier model analyzes: which models are performing well, where are the gaps,
   are there enough confirmed annotations to fine-tune a local classifier?
4. Output: updated `routing_rules`, performance notes → stored in `model_performance`
5. Suggestions for the user: "You have 800 confirmed portrait annotations —
   enough to fine-tune a CLIP classifier for this library specifically"

### Future: Memento Takes Over

Memento already has access to Docker, files, git, and system state. As it accumulates:
- Model performance history for this library
- Routing rules derived from empirical results
- Coverage maps showing what's annotated and what isn't
- Patterns in what the user confirms vs. rejects

It can progressively take on:
- Scheduling curation sessions ("500 images from 2015 have no type annotation")
- Proposing routing updates ("qwen3-vl outperforms llava on scan detection, 94% vs 71%")
- Triggering ML passes on newly imported images
- Generating calibration reports without a frontier model

The frontier model is no longer needed when Memento can evaluate and route reliably on
this library's specific distribution.

---

## Phased Implementation

### Phase 1 — Foundation (schema + seed data)
- `facets`, `terms`, `annotations` tables with indexes
- `annotation_suggestions`, `auto_apply_rules` tables
- Seed default facets and vocabulary terms
- Migration for `people`, `named_places`, `events`, `image_people`, `image_events`
- Coverage score computation

### Phase 2 — ML Pipeline
- Ollama client in Lumina backend
- CLIP integration for zero-shot classification
- qwen3-vl integration for captioning and genre detection
- Suggestion queue population (background job)
- Batch review API endpoints

### Phase 3 — Curation UI
- Suggestion review panel (batch confirm/reject)
- "Name the people" session UI (face cluster → person)
- Event labeling UI (cluster → named event)
- Coverage dashboard: what's annotated, what needs attention
- Auto-apply rule management

### Phase 4 — Compound Search
- Faceted filter UI (sidebar: filter by any facet/term)
- Age-at-time query support
- Named place and event filters
- Similarity search integration

### Phase 5 — Meta-model & Memento
- `model_performance` tracking (populated from suggestion outcomes)
- `routing_rules` table + routing logic in ML pipeline
- Calibration session tooling (frontier model integration)
- Memento hooks: coverage reports, session scheduling, performance summaries

---

## What This Enables at Maturity

- *"Show me all family archive photos of Mom outdoors, picks only"*
- *"Find scans from before 1980 that have no event label"*
- *"Photos of Jake age 6–10 at named places we've visited"*
- *"Work documentation photos from 2022 conferences"*
- *"Images similar to this one that are unreviewed"*
- *"What percentage of my 2015 photos have a purpose tag?"*

The archive becomes a queryable, semantically-rich library that improves with every
curation session, without ever requiring a complete reprocessing pass.
