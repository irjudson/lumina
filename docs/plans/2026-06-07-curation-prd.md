# Lumina Curation System — Product Requirements Document

> **For Claude:** Use superpowers:executing-plans or superpowers:subagent-driven-development
> to implement this plan task-by-task.

**Goal:** A question-first, folksonomy-driven curation system that makes a 76,000+ image
archive progressively findable through incremental human-guided, ML-assisted enrichment.

**Architecture:** Unified tag model (folksonomy), ML surfaces groups, human assigns meaning.
Home screen orients and focuses — the grid is a workspace for a scoped task, never the
default view.

**Tech Stack:** FastAPI + PostgreSQL backend, Vue 3 + Pinia + TypeScript + TailwindCSS
frontend, Ollama via shared-infra (`http://ollama:11434`), CLIP + FAISS + InsightFace local.

---

## Design Decisions (locked)

These were resolved in design dialogue and are not open for re-interpretation:

**Folksonomy — no pre-defined taxonomy.**
ML surfaces groups. The user names, merges, splits, or deletes them. Names become tags.
Tags optionally get parents (hierarchy). The full structure — including axes/dimensions —
emerges from practice. Nothing is seeded except what already exists (see Migration).

**Everything is a tag.**
Collections and tags are the same concept. A named group of images with a label.
Tags can be hierarchical. The existing collections system is unified into tags.

**ML narrows the space, human decides everything ambiguous.**
ML uses all methods available — clustering, visual similarity, hyperdimensional embedding
analysis, historical human decisions — to narrow the possibility space. It never applies
a confirmed annotation without human review unless an explicit auto-apply rule exists.
Auto-apply rules gate on *empirical* precision (measured from human feedback), not
raw model confidence scores.

**ML triggers: automatic + scheduled.**
After every import: ML pipeline runs as a background job on new images.
Continuously: a scheduled improvement job runs on the existing library — propagating
newly-named tags to similar unlabeled images, surfacing new group candidates, updating
routing based on accumulated feedback.

**People system: name is the key.**
No birthdates. Age is inferred by ML from face appearance + capture timestamp
(InsightFace age estimation, stored as `inferred_age` per image-person link).
The person record is minimal: name + human-added metadata (relationships, notes)
that accretes from practice. Existing named face clusters migrate automatically.

**Home is a focused queue, not a grid.**
76,000 images in a grid is paralyzing. The home screen surfaces what needs attention
in digestible, scoped tasks. The grid is a workspace that appears when a task is
selected — always scoped, never the full library.

**Grid review: bulk select/deselect.**
When reviewing a scoped set, the user works in a grid with bulk selection.
Keyboard-driven interaction (Lightroom/Darktable paradigm).

**Question-first search.**
The primary search mechanism is natural language / tag query at the top of any
scoped grid. CLIP text-to-image similarity enables queries like "family archival scans"
against the FAISS index even before those tags exist.

**Last Import is a view, not a collection.**
Implemented as a filter on `imported_at` for the most recent import batch.
No persistent record, no collection entry.

**Migration:**
- Named face clusters → migrate to tags automatically (people tags)
- Travel collection → migrates to tags automatically
- `family_personal`, `work_professional`, `projects`, `archival` → deleted (all empty)

**UX: two modes, minimal left panel.**
- **Library** — browse by tag, search, review scoped sets
- **Curate** — proactive ML group queue (unnamed groups needing attention)
- Left panel: tag tree only (grows from practice). No filter controls, no heavy sections.
- Import: a button, not a navigation destination.
- Filter bar: appears at top of grid when active, hidden when not.

---

## Phase 1 Scope

Phase 1 delivers the core loop end-to-end:
**ML surfaces groups → user reviews → user names → tag created → images annotated.**

### In scope:
- Database schema (tags, ml_groups, annotation_suggestions, model_performance, routing_rules)
- Migration (face clusters + travel → tags, delete empty collections)
- ML pipeline: CLIP clustering → ml_groups, qwen3-vl captions via Ollama → suggestions
- Background job: triggered by import + scheduled improvement run
- Home screen: focused queue
- Group review UI: scoped grid with bulk select/deselect, naming controls
- Tag tree in left panel (replaces current collection list)
- Search: text query → CLIP similarity → candidate grid

### Explicitly out of scope for Phase 1:
- Compound faceted search (Phase 4)
- Age-at-time queries (Phase 4)
- Named places with GPS bounds (Phase 3)
- Named events with date ranges (Phase 3)
- Auto-apply rules UI (Phase 3)
- Model performance dashboard (Phase 5)
- Print/share/publish output (future)
- XMP/sidecar export (future)

---

## Data Model

### Tags (the universal annotation primitive)

```sql
CREATE TABLE tags (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_id  UUID NOT NULL REFERENCES catalogs(id),
    slug        TEXT NOT NULL,
    label       TEXT NOT NULL,
    parent_id   UUID REFERENCES tags(id),
    notes       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (catalog_id, slug)
);

CREATE INDEX idx_tags_catalog ON tags (catalog_id);
CREATE INDEX idx_tags_parent ON tags (parent_id);
```

```sql
-- Confirmed annotations (human-reviewed or auto-applied by explicit rule)
CREATE TABLE image_tags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id        TEXT NOT NULL,
    tag_id          UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    confidence      FLOAT DEFAULT 1.0,       -- 1.0 = human confirmed
    source          TEXT NOT NULL,           -- 'human', 'ml_confirmed', 'auto_rule'
    model           TEXT,
    annotated_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (image_id, tag_id)
);

CREATE INDEX idx_image_tags_image ON image_tags (image_id);
CREATE INDEX idx_image_tags_tag ON image_tags (tag_id);
```

### ML Groups (surfaced clusters pending human review)

```sql
CREATE TABLE ml_groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_id      UUID NOT NULL REFERENCES catalogs(id),
    method          TEXT NOT NULL,           -- 'clip_cluster', 'face_cluster',
                                             --   'temporal_geo', 'visual_similarity'
    label_hint      TEXT,                    -- ML-drafted name suggestion
    image_count     INT NOT NULL DEFAULT 0,
    sample_image_ids JSONB DEFAULT '[]',     -- up to 9 representative image IDs
    signals         JSONB DEFAULT '{}',      -- evidence: cluster_id, centroid, geo_center, etc.
    status          TEXT DEFAULT 'pending',  -- 'pending', 'named', 'merged', 'split', 'deleted'
    tag_id          UUID REFERENCES tags(id),-- set when named
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ
);

CREATE INDEX idx_ml_groups_catalog_status ON ml_groups (catalog_id, status);
```

```sql
-- Which images belong to which ML group
CREATE TABLE ml_group_images (
    group_id    UUID NOT NULL REFERENCES ml_groups(id) ON DELETE CASCADE,
    image_id    TEXT NOT NULL,
    score       FLOAT,                       -- similarity score within group
    PRIMARY KEY (group_id, image_id)
);
```

### Annotation Suggestions (ML proposals, not yet confirmed)

```sql
CREATE TABLE annotation_suggestions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id        TEXT NOT NULL,
    tag_id          UUID REFERENCES tags(id),        -- null if suggesting a new tag
    suggested_label TEXT,                            -- for new tags not yet created
    confidence      FLOAT NOT NULL,                  -- raw model confidence (not used for auto-apply)
    empirical_precision FLOAT,                       -- measured from feedback history
    model           TEXT NOT NULL,
    evidence        JSONB DEFAULT '{}',
    status          TEXT DEFAULT 'pending',          -- 'pending','confirmed','rejected','auto_applied'
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_suggestions_image ON annotation_suggestions (image_id);
CREATE INDEX idx_suggestions_status ON annotation_suggestions (status);
```

### People (structured companion to person tags)

```sql
CREATE TABLE people (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_id      UUID NOT NULL REFERENCES catalogs(id),
    tag_id          UUID REFERENCES tags(id),        -- the person's tag in the folksonomy
    name            TEXT NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE image_people (
    image_id        TEXT NOT NULL,
    person_id       UUID NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    confidence      FLOAT DEFAULT 1.0,
    source          TEXT NOT NULL,                   -- 'human', 'face_recognition', 'ml_confirmed'
    inferred_age    FLOAT,                           -- ML-estimated age at capture time
    PRIMARY KEY (image_id, person_id)
);

CREATE INDEX idx_image_people_person ON image_people (person_id);
```

### Model Performance & Routing

```sql
CREATE TABLE model_performance (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model           TEXT NOT NULL,
    task            TEXT NOT NULL,                   -- 'cluster', 'caption', 'classify_type'
    precision       FLOAT,
    recall          FLOAT,
    sample_count    INT,
    evaluated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Learned routing: which model to use for which task
CREATE TABLE routing_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task            TEXT NOT NULL,
    image_context   JSONB DEFAULT '{}',              -- conditions: has_faces, file_type, etc.
    model           TEXT NOT NULL,
    priority        INT DEFAULT 0,
    source          TEXT NOT NULL,                   -- 'default', 'memento', 'user'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### Auto-Apply Rules

```sql
CREATE TABLE auto_apply_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_id      UUID NOT NULL REFERENCES catalogs(id),
    tag_id          UUID REFERENCES tags(id),
    model           TEXT,
    min_empirical_precision FLOAT NOT NULL,          -- gates on measured precision, not model confidence
    granted_at      TIMESTAMPTZ DEFAULT NOW(),
    notes           TEXT
);
```

---

## ML Pipeline

### Models (all via Ollama at `http://ollama:11434` or local)

| Model | Task | Trigger |
|---|---|---|
| CLIP ViT-L/14 (local) | Embedding + zero-shot classification | All images |
| HDBSCAN on CLIP embeddings | Cluster formation → ml_groups | Scheduled |
| `qwen3-vl` (Ollama) | Caption draft, label hint for groups | On group formation |
| `qwen2.5:14b` (Ollama) | Routing decisions, batch reasoning | On calibration |
| InsightFace (local) | Face detection + age estimation | All images |
| DBSCAN on GPS + timestamp | Temporal/geo cluster formation | Scheduled |
| Laplacian variance (CPU) | Sharpness scoring | All images |

### Pipeline Stages

**Stage 1 — Per-image (on import):**
1. CLIP embedding → store in FAISS (already exists, extend if needed)
2. InsightFace → face bounding boxes, cluster assignment, age estimate
3. Laplacian variance → sharpness score → annotation_suggestion
4. `qwen3-vl` → caption + rough type hint → annotation_suggestion

**Stage 2 — Batch (scheduled improvement job):**
1. HDBSCAN on CLIP embeddings → form/update ml_groups
2. DBSCAN on GPS + timestamp → form/update temporal_geo ml_groups
3. For each new ml_group: `qwen3-vl` drafts a label_hint from sample images
4. Propagate: for each newly named tag, find unlabeled similar images → annotation_suggestions
5. Update empirical_precision on annotation_suggestions from recent feedback
6. Update routing_rules from model_performance history

### Routing

Default routing rules are seeded at startup. Updated by the scheduled job as empirical
precision data accumulates. The routing table determines which model runs for which task
on which type of image — e.g., face clusters use InsightFace, temporal events use
DBSCAN, visual genre uses CLIP, label hints use qwen3-vl.

---

## UX — Home Screen

The home screen orients and focuses. It never shows the full library grid.

### Sections (in priority order):

**Continue** (if a session was in progress)
- "You were reviewing [group name] — 34 images remaining"
- One-click to resume

**Needs Attention** (scoped tasks, ordered by recency + size)
- "[N] images from your last import are untagged" → opens scoped grid
- "[N] unnamed groups found this week" → opens curate queue
- "[N] ML suggestions waiting for review" → opens suggestion review

**Recent** (last 5 named tags or completed sessions)
- Quick access to recently created tags
- Counts: how many images, when created

**Ask** (question-first search)
- Prominent search bar
- CLIP text-to-image similarity against FAISS index
- Returns a scoped grid of candidates

---

## UX — Scoped Grid (workspace)

Appears when a task is selected from home or a tag is clicked. Never the full library.

### Controls:
- **Top bar**: task title ("Reviewing: family scans — 200 images"), progress, Done button
- **Filter bar**: appears above grid when search/filter is active (hidden otherwise)
- **Grid**: image thumbnails, variable density
- **Bulk select**: shift-click range, cmd-click individual, "select all" button
- **Keyboard shortcuts** (Lightroom-style):
  - `Space` — toggle select current image
  - `→ ←` — navigate
  - `A` — select all
  - `D` — deselect all
  - `Enter` — confirm selection as tag / proceed

### Selection actions (appear when images are selected):
- Add tag
- Remove tag
- Mark as reviewed (dismiss from suggestion queue)
- Open in detail view

---

## UX — Curate Mode (proactive group queue)

Accessed via top navigation. Shows ML-surfaced groups pending naming.

### Layout:
- **Left**: list of pending groups (count, method, label_hint)
- **Center**: selected group's images in a scoped grid
- **Right**: group signals (what formed this cluster), naming controls

### Group actions:
- **Name it** — type a label → creates a tag → annotates all images in group
- **Skip** — come back later
- **Delete** — not a meaningful group, suppress
- **Merge** — with another named tag or group
- **Split** — re-cluster with different parameters (or manual selection)

---

## UX — Left Panel (tag tree)

Always visible in Library mode. Replaces current collection list entirely.

- Flat list by default, indented when hierarchy exists
- Search/filter at top of panel
- Click a tag → scoped grid of images with that tag
- Count badge on each tag
- "+" button to create a tag manually (without ML group)

---

## Migration Plan

Run as a one-time migration at Phase 1 deploy:

1. Create all new tables
2. **Face clusters → tags**: for each named face cluster, create a `tags` record
   (label = person name) + `people` record + `image_tags` records for all cluster members
3. **Travel collection → tag**: create a `tags` record (label = "Travel") with child
   tags for each travel sub-collection (by country/region as currently geocoded)
4. **Delete**: `family_personal`, `work_professional`, `projects`, `archival` collections
5. **Last Import collection**: delete; replace with view filter on `imported_at`
6. Seed default routing_rules for initial model assignments

---

## Acceptance Criteria

### Schema
- [ ] All tables created with correct indexes and foreign keys
- [ ] Migration runs without data loss on existing catalog
- [ ] Face clusters visible as tags in left panel after migration
- [ ] Travel sub-collections visible as child tags after migration
- [ ] Empty collections gone

### ML Pipeline
- [ ] New import triggers ML job; job produces ml_groups and annotation_suggestions
- [ ] Scheduled job runs and finds clusters in existing library
- [ ] qwen3-vl produces label_hint for each ml_group
- [ ] Sharpness scores written as annotation_suggestions for new images

### Home Screen
- [ ] Home shows "needs attention" items, not a grid
- [ ] Each item links to a scoped task
- [ ] "Continue" appears if a session was in progress
- [ ] Search bar performs CLIP text-to-image query against FAISS, returns scoped grid

### Curate Mode
- [ ] Pending ml_groups appear in curate queue
- [ ] Grid shows group images with bulk select
- [ ] Naming a group creates a tag and annotates all member images
- [ ] Delete, skip, merge actions work

### Library Mode
- [ ] Left panel shows tag tree with counts
- [ ] Clicking a tag opens scoped grid (not full library)
- [ ] Filter bar appears above grid when active, hidden when empty
- [ ] Full library grid is NOT the default view

### People
- [ ] Named face clusters migrated to tags + people records
- [ ] inferred_age populated for images with detected faces

---

## Out of Scope

Explicitly deferred — do not implement in Phase 1:

- Compound faceted search across multiple tags simultaneously
- Named places with GPS radius bounds
- Named events with date ranges
- Auto-apply rules management UI
- Age-at-time range queries
- Model performance dashboard
- Fine-tuning local models
- Print / share / publish output flows
- XMP sidecar export
- Multi-user / permissions
- Memento calibration integration
