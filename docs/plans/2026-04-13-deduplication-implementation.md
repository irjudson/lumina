# Layered Deduplication System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a five-layer duplicate detection pipeline with provenance-tracked archival, suppression memory, and per-catalog threshold adaptation.

**Architecture:** Pure-function detection layers (L1–L5) feed a `duplicate_candidates` table. User decisions flow through `duplicate_decisions` into `archived_images` (full provenance copy) and `suppression_pairs` (permanent do-not-resurface index). A threshold EMA loop adapts per-layer Hamming thresholds from user feedback.

**Tech Stack:** SQLAlchemy, FastAPI, PIL (multi-resolution dhash already parameterized), pure Python BK-tree (no new deps), PostgreSQL JSONB for detection metadata.

**Design doc:** `docs/plans/2026-04-13-deduplication-design.md`

---

## Task 1: Schema — Models

**Files:**
- Modify: `lumina/db/models.py`
- Test: `tests/db/test_dedup_models.py`

### Step 1: Write failing model import test

```python
# tests/db/test_dedup_models.py
def test_dedup_models_importable():
    from lumina.db.models import (
        DuplicateCandidate,
        DuplicateDecision,
        ArchivedImage,
        DetectionThreshold,
        SuppressionPair,
    )
    assert DuplicateCandidate.__tablename__ == "duplicate_candidates"
    assert DuplicateDecision.__tablename__ == "duplicate_decisions"
    assert ArchivedImage.__tablename__ == "archived_images"
    assert DetectionThreshold.__tablename__ == "detection_thresholds"
    assert SuppressionPair.__tablename__ == "suppression_pairs"
```

### Step 2: Run to confirm it fails
```bash
cd /home/irjudson/Projects/lumina
pytest tests/db/test_dedup_models.py::test_dedup_models_importable -v
```
Expected: `ImportError` or `AttributeError`

### Step 3: Add models to `lumina/db/models.py`

Add `dhash_16` and `dhash_32` to the `Image` class (after the existing `whash` column at line ~143):
```python
    dhash_16 = Column(Text)   # 256-bit hash for L4 preview detection (scale > 0.5)
    dhash_32 = Column(Text)   # 1024-bit hash for L4 preview detection (scale > 0.25)
```

Append new model classes at the end of `lumina/db/models.py` (before the final `__repr__`s):
```python
class DuplicateCandidate(Base):
    """Raw output of the duplicate detection pipeline — one row per pair per layer."""

    __tablename__ = "duplicate_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_id_a = Column(Text, ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    image_id_b = Column(Text, ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    layer = Column(
        String(50),
        nullable=False,
    )  # exact | reimport | format_variant | preview | near_duplicate
    confidence = Column(Float, nullable=False)
    verify_carefully = Column(Boolean, default=False, nullable=False)
    verify_reason = Column(Text)
    detection_meta = Column(JSONB, nullable=False, default={})
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint("image_id_a", "image_id_b", "layer", name="uq_candidate_pair_layer"),
    )


class DuplicateDecision(Base):
    """Immutable audit log of every user decision on a duplicate candidate."""

    __tablename__ = "duplicate_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4)
    candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("duplicate_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision = Column(String(50), nullable=False)  # confirmed_duplicate | not_duplicate | deferred
    primary_id = Column(Text, ForeignKey("images.id", ondelete="SET NULL"))
    decided_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes = Column(Text)


class ArchivedImage(Base):
    """Full copy of an images row at archive time, with provenance chain."""

    __tablename__ = "archived_images"

    # Copy of images primary key
    id = Column(Text, primary_key=True)
    catalog_id = Column(UUID(as_uuid=True), nullable=False)
    source_path = Column(Text, nullable=False)
    file_type = Column(String, nullable=False)
    checksum = Column(Text, nullable=False)
    size_bytes = Column(BigInteger)
    dates = Column(JSONB, nullable=False, default={})
    metadata_json = Column("metadata", JSONB, nullable=False, default={})
    thumbnail_path = Column(Text)
    dhash = Column(Text)
    ahash = Column(Text)
    whash = Column(Text)
    dhash_16 = Column(Text)
    dhash_32 = Column(Text)
    quality_score = Column(Integer)
    capture_time = Column(DateTime)
    camera_make = Column(String(255))
    camera_model = Column(String(255))
    width = Column(Integer)
    height = Column(Integer)
    format = Column(String(20))
    latitude = Column(Float)
    longitude = Column(Float)
    processing_flags = Column(JSONB, nullable=False, default={})
    created_at = Column(DateTime)

    # Provenance fields
    archived_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    archive_reason = Column(String(50), nullable=False)  # mirrors layer name
    decision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("duplicate_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    primary_image_id = Column(Text, nullable=False)
    original_catalog_id = Column(UUID(as_uuid=True), nullable=False)
    restoration_path = Column(Text)


class DetectionThreshold(Base):
    """Per-catalog per-layer learning state for threshold adaptation."""

    __tablename__ = "detection_thresholds"

    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    layer = Column(String(50), primary_key=True)
    threshold = Column(Float, nullable=False)
    confirmed_count = Column(Integer, default=0, nullable=False)
    rejected_count = Column(Integer, default=0, nullable=False)
    last_run_threshold = Column(Float)
    last_updated = Column(DateTime, default=datetime.utcnow)


class SuppressionPair(Base):
    """Permanent do-not-resurface index for reviewed pairs."""

    __tablename__ = "suppression_pairs"

    id_a = Column(Text, primary_key=True)   # lexicographically smaller image ID
    id_b = Column(Text, primary_key=True)   # lexicographically larger image ID
    decision = Column(String(50), nullable=False)  # confirmed_duplicate | not_duplicate
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

### Step 4: Run test to confirm it passes
```bash
pytest tests/db/test_dedup_models.py::test_dedup_models_importable -v
```
Expected: `PASSED`

### Step 5: Commit
```bash
git add lumina/db/models.py tests/db/test_dedup_models.py
git commit -m "feat: add deduplication data models (candidates, decisions, archive, thresholds, suppression)"
```

---

## Task 2: Schema — Database Migration

**Files:**
- Create: `lumina/db/migrations/dedup_schema.py`
- Test: run against the live database

### Step 1: Write migration script

```python
# lumina/db/migrations/dedup_schema.py
"""Migration: add deduplication tables and dhash_16/dhash_32 columns."""

from sqlalchemy import text


def upgrade(engine):
    """Apply deduplication schema changes."""
    with engine.begin() as conn:
        # Add multi-resolution hash columns to images
        conn.execute(text("""
            ALTER TABLE images
            ADD COLUMN IF NOT EXISTS dhash_16 TEXT,
            ADD COLUMN IF NOT EXISTS dhash_32 TEXT
        """))

        # duplicate_candidates
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS duplicate_candidates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
                image_id_a TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                image_id_b TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                layer VARCHAR(50) NOT NULL,
                confidence FLOAT NOT NULL,
                verify_carefully BOOLEAN NOT NULL DEFAULT FALSE,
                verify_reason TEXT,
                detection_meta JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMP,
                CONSTRAINT uq_candidate_pair_layer UNIQUE (image_id_a, image_id_b, layer)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_candidates_catalog
            ON duplicate_candidates(catalog_id, reviewed_at)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_candidates_layer
            ON duplicate_candidates(catalog_id, layer, confidence DESC)
        """))

        # duplicate_decisions
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS duplicate_decisions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                candidate_id UUID NOT NULL REFERENCES duplicate_candidates(id) ON DELETE RESTRICT,
                decision VARCHAR(50) NOT NULL,
                primary_id TEXT REFERENCES images(id) ON DELETE SET NULL,
                decided_at TIMESTAMP NOT NULL DEFAULT NOW(),
                notes TEXT
            )
        """))

        # archived_images
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS archived_images (
                id TEXT PRIMARY KEY,
                catalog_id UUID NOT NULL,
                source_path TEXT NOT NULL,
                file_type VARCHAR NOT NULL,
                checksum TEXT NOT NULL,
                size_bytes BIGINT,
                dates JSONB NOT NULL DEFAULT '{}',
                metadata JSONB NOT NULL DEFAULT '{}',
                thumbnail_path TEXT,
                dhash TEXT,
                ahash TEXT,
                whash TEXT,
                dhash_16 TEXT,
                dhash_32 TEXT,
                quality_score INTEGER,
                capture_time TIMESTAMP,
                camera_make VARCHAR(255),
                camera_model VARCHAR(255),
                width INTEGER,
                height INTEGER,
                format VARCHAR(20),
                latitude FLOAT,
                longitude FLOAT,
                processing_flags JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMP,
                archived_at TIMESTAMP NOT NULL DEFAULT NOW(),
                archive_reason VARCHAR(50) NOT NULL,
                decision_id UUID NOT NULL REFERENCES duplicate_decisions(id) ON DELETE RESTRICT,
                primary_image_id TEXT NOT NULL,
                original_catalog_id UUID NOT NULL,
                restoration_path TEXT
            )
        """))

        # detection_thresholds
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS detection_thresholds (
                catalog_id UUID NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
                layer VARCHAR(50) NOT NULL,
                threshold FLOAT NOT NULL,
                confirmed_count INTEGER NOT NULL DEFAULT 0,
                rejected_count INTEGER NOT NULL DEFAULT 0,
                last_run_threshold FLOAT,
                last_updated TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (catalog_id, layer)
            )
        """))

        # suppression_pairs
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS suppression_pairs (
                id_a TEXT NOT NULL,
                id_b TEXT NOT NULL,
                decision VARCHAR(50) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                PRIMARY KEY (id_a, id_b)
            )
        """))


def downgrade(engine):
    """Reverse deduplication schema changes."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS suppression_pairs CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS detection_thresholds CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS archived_images CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS duplicate_decisions CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS duplicate_candidates CASCADE"))
        conn.execute(text("ALTER TABLE images DROP COLUMN IF EXISTS dhash_16"))
        conn.execute(text("ALTER TABLE images DROP COLUMN IF EXISTS dhash_32"))
```

### Step 2: Run migration against live database
```bash
cd /home/irjudson/Projects/lumina
python -c "
from lumina.db.connection import engine
from lumina.db.migrations.dedup_schema import upgrade
upgrade(engine)
print('Migration complete')
"
```
Expected: `Migration complete`

### Step 3: Verify tables exist
```bash
python -c "
from lumina.db.connection import engine
from sqlalchemy import text, inspect
insp = inspect(engine)
tables = insp.get_table_names()
for t in ['duplicate_candidates','duplicate_decisions','archived_images','detection_thresholds','suppression_pairs']:
    print(t, '✓' if t in tables else '✗ MISSING')
cols = [c['name'] for c in insp.get_columns('images')]
print('dhash_16', '✓' if 'dhash_16' in cols else '✗ MISSING')
print('dhash_32', '✓' if 'dhash_32' in cols else '✗ MISSING')
"
```
Expected: all `✓`

### Step 4: Commit
```bash
git add lumina/db/migrations/dedup_schema.py
git commit -m "feat: dedup schema migration (5 new tables, dhash_16/32 columns)"
```

---

## Task 3: Multi-Resolution Hashing (`hash_images_v2`)

**Files:**
- Modify: `lumina/analysis/hashing.py`
- Create: `lumina/jobs/definitions/hash_v2.py`
- Test: `tests/analysis/test_hashing_pure.py` (extend existing)

### Step 1: Write failing test for multi-resolution hashes

Add to `tests/analysis/test_hashing_pure.py`:
```python
def test_compute_all_hashes_v2_returns_multi_res(shared_test_images):
    from lumina.analysis.hashing import compute_all_hashes_v2
    result = compute_all_hashes_v2(shared_test_images / "red.jpg")
    assert "dhash_8" in result
    assert "dhash_16" in result
    assert "dhash_32" in result
    assert len(result["dhash_8"]) == 16    # 64-bit = 16 hex chars
    assert len(result["dhash_16"]) == 64   # 256-bit = 64 hex chars
    assert len(result["dhash_32"]) == 256  # 1024-bit = 256 hex chars

def test_dhash_16_captures_more_detail(shared_test_images):
    from lumina.analysis.hashing import compute_dhash
    h8 = compute_dhash(shared_test_images / "gradient1.jpg", hash_size=8)
    h16 = compute_dhash(shared_test_images / "gradient1.jpg", hash_size=16)
    assert len(h8) == 16
    assert len(h16) == 64
    # Different resolutions should produce different length hashes
    assert len(h8) != len(h16)
```

### Step 2: Run to confirm failure
```bash
pytest tests/analysis/test_hashing_pure.py::test_compute_all_hashes_v2_returns_multi_res -v
```
Expected: `ImportError: cannot import name 'compute_all_hashes_v2'`

### Step 3: Add `compute_all_hashes_v2` to `lumina/analysis/hashing.py`

Append after the existing `compute_all_hashes` function:
```python
def compute_all_hashes_v2(
    image_path: Union[Path, str],
) -> Dict[str, str]:
    """Compute multi-resolution dhash for deduplication pipeline.

    Returns dhash at three sizes:
    - dhash_8:  64-bit  (existing, for L5 near-duplicate)
    - dhash_16: 256-bit (for L4 preview, scale > 0.5)
    - dhash_32: 1024-bit (for L4 preview, scale > 0.25)

    Also returns ahash and whash at size 8 for backwards compatibility.
    """
    return {
        "dhash_8":  compute_dhash(image_path, hash_size=8),
        "dhash_16": compute_dhash(image_path, hash_size=16),
        "dhash_32": compute_dhash(image_path, hash_size=32),
        "ahash":    compute_ahash(image_path, hash_size=8),
        "whash":    compute_whash(image_path, hash_size=8),
    }
```

### Step 4: Run tests to confirm pass
```bash
pytest tests/analysis/test_hashing_pure.py::test_compute_all_hashes_v2_returns_multi_res tests/analysis/test_hashing_pure.py::test_dhash_16_captures_more_detail -v
```
Expected: both `PASSED`

### Step 5: Write job definition

```python
# lumina/jobs/definitions/hash_v2.py
"""Job definition: compute multi-resolution hashes for deduplication pipeline."""

from typing import Any, Callable, Dict, List, Optional

from ..framework import ParallelJob, register_job

DEFAULT_THRESHOLDS = {
    "format_variant": 4.0,
    "preview": 3.0,
    "near_duplicate": 8.0,
}


def discover_images_needing_hashes(
    catalog_id: str,
    images_provider: Optional[Callable] = None,
) -> List[str]:
    """Find images missing dhash_16 or dhash_32."""
    if images_provider:
        return images_provider(catalog_id)

    from lumina.db.models import Image
    from lumina.db.connection import SessionLocal

    with SessionLocal() as session:
        images = (
            session.query(Image.id)
            .filter(Image.catalog_id == catalog_id)
            .filter((Image.dhash_16.is_(None)) | (Image.dhash_32.is_(None)))
            .all()
        )
        return [str(row.id) for row in images]


def compute_hashes_v2(
    image_id: str,
    catalog_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Compute and store multi-resolution hashes for one image."""
    from lumina.db.models import Image
    from lumina.db.connection import SessionLocal
    from lumina.analysis.hashing import compute_all_hashes_v2

    with SessionLocal() as session:
        image = session.query(Image).filter(Image.id == image_id).first()
        if not image:
            return {"image_id": image_id, "success": False, "error": "not found"}

        try:
            hashes = compute_all_hashes_v2(image.source_path)
            image.dhash = hashes["dhash_8"]
            image.dhash_16 = hashes["dhash_16"]
            image.dhash_32 = hashes["dhash_32"]
            image.ahash = hashes["ahash"]
            image.whash = hashes["whash"]
            session.commit()
            return {"image_id": image_id, "success": True}
        except Exception as e:
            session.rollback()
            return {"image_id": image_id, "success": False, "error": str(e)}


def finalize_hash_v2(
    results: List[Dict[str, Any]],
    catalog_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Summarize hash computation results and seed default thresholds."""
    from lumina.db.connection import SessionLocal
    from lumina.db.models import DetectionThreshold, Catalog
    import uuid

    successes = sum(1 for r in results if r.get("success"))
    failures = sum(1 for r in results if not r.get("success"))

    # Seed default thresholds for this catalog if not already set
    with SessionLocal() as session:
        catalog = session.query(Catalog).filter(
            Catalog.id == uuid.UUID(catalog_id)
        ).first()
        if catalog:
            for layer, default in DEFAULT_THRESHOLDS.items():
                exists = session.query(DetectionThreshold).filter(
                    DetectionThreshold.catalog_id == uuid.UUID(catalog_id),
                    DetectionThreshold.layer == layer,
                ).first()
                if not exists:
                    session.add(DetectionThreshold(
                        catalog_id=uuid.UUID(catalog_id),
                        layer=layer,
                        threshold=default,
                        last_run_threshold=default,
                    ))
            session.commit()

    return {
        "catalog_id": catalog_id,
        "hashed": successes,
        "failed": failures,
    }


hash_v2_job = register_job(
    ParallelJob(
        name="hash_images_v2",
        discover=discover_images_needing_hashes,
        process=compute_hashes_v2,
        finalize=finalize_hash_v2,
        batch_size=500,
    )
)
```

### Step 6: Write job test

```python
# tests/jobs/test_hash_v2.py
def test_discover_images_needing_hashes_uses_provider():
    from lumina.jobs.definitions.hash_v2 import discover_images_needing_hashes
    result = discover_images_needing_hashes("cat-1", images_provider=lambda cid: ["a", "b"])
    assert result == ["a", "b"]

def test_compute_hashes_v2_handles_missing_image():
    from lumina.jobs.definitions.hash_v2 import compute_hashes_v2
    result = compute_hashes_v2("nonexistent-id", "cat-1")
    assert result["success"] is False

def test_finalize_hash_v2_returns_counts():
    from lumina.jobs.definitions.hash_v2 import finalize_hash_v2
    results = [{"success": True}, {"success": True}, {"success": False, "error": "x"}]
    # Use a catalog_id that won't exist — finalize handles gracefully
    out = finalize_hash_v2(results, "00000000-0000-0000-0000-000000000000")
    assert out["hashed"] == 2
    assert out["failed"] == 1
```

### Step 7: Run tests
```bash
pytest tests/jobs/test_hash_v2.py -v
```
Expected: all `PASSED`

### Step 8: Register job in job_implementations.py

In `lumina/jobs/job_implementations.py`, in the `JOB_HANDLERS` dict (around line 1244), add:
```python
"hash_images_v2": lambda ctx: _run_framework_job(ctx, "hash_images_v2"),
```

Also ensure `hash_v2` job definition is imported at module level by adding near the other definition imports:
```python
from .definitions import hash_v2  # noqa: F401 - registers hash_images_v2 job
```

### Step 9: Commit
```bash
git add lumina/analysis/hashing.py lumina/jobs/definitions/hash_v2.py lumina/jobs/job_implementations.py tests/analysis/test_hashing_pure.py tests/jobs/test_hash_v2.py
git commit -m "feat: multi-resolution hashing (dhash_16/32) and hash_images_v2 job"
```

---

## Task 4: Detection Pipeline Foundation + L1 + L2

**Files:**
- Create: `lumina/analysis/dedup/__init__.py`
- Create: `lumina/analysis/dedup/types.py`
- Create: `lumina/analysis/dedup/pipeline.py`
- Create: `lumina/analysis/dedup/layers/__init__.py`
- Create: `lumina/analysis/dedup/layers/l1_exact.py`
- Create: `lumina/analysis/dedup/layers/l2_reimport.py`
- Test: `tests/analysis/test_dedup_pipeline.py`

### Step 1: Write failing tests

```python
# tests/analysis/test_dedup_pipeline.py
def test_candidate_pair_ordering():
    """image_id_a is always the lex-smaller of the two."""
    from lumina.analysis.dedup.types import CandidatePair
    p = CandidatePair(image_id_a="zzz", image_id_b="aaa", layer="exact",
                      confidence=1.0, detection_meta={})
    assert p.image_id_a == "aaa"
    assert p.image_id_b == "zzz"

def test_l1_exact_uses_checksum():
    from lumina.analysis.dedup.layers.l1_exact import detect_exact
    images = [
        {"id": "img-1", "checksum": "abc123", "source_path": "/a/1.jpg", "created_at": None},
        {"id": "img-2", "checksum": "abc123", "source_path": "/a/2.jpg", "created_at": None},
        {"id": "img-3", "checksum": "zzz999", "source_path": "/a/3.jpg", "created_at": None},
    ]
    pairs = list(detect_exact(images))
    assert len(pairs) == 1
    assert pairs[0].layer == "exact"
    assert pairs[0].confidence == 1.0
    assert set([pairs[0].image_id_a, pairs[0].image_id_b]) == {"img-1", "img-2"}

def test_l2_reimport_uses_source_path():
    from lumina.analysis.dedup.layers.l2_reimport import detect_reimport
    images = [
        {"id": "img-1", "checksum": "aaa", "source_path": "/photos/x.jpg", "created_at": "2024-01-01"},
        {"id": "img-2", "checksum": "bbb", "source_path": "/photos/x.jpg", "created_at": "2024-06-01"},
        {"id": "img-3", "checksum": "ccc", "source_path": "/photos/y.jpg", "created_at": "2024-01-01"},
    ]
    pairs = list(detect_reimport(images))
    assert len(pairs) == 1
    assert pairs[0].layer == "reimport"

def test_pipeline_skips_suppressed():
    from lumina.analysis.dedup.pipeline import filter_suppressed
    candidates = [
        type("C", (), {"image_id_a": "a", "image_id_b": "b"})(),
        type("C", (), {"image_id_a": "c", "image_id_b": "d"})(),
    ]
    suppressed = {("a", "b")}
    result = list(filter_suppressed(candidates, suppressed))
    assert len(result) == 1
    assert result[0].image_id_a == "c"
```

### Step 2: Run to confirm failure
```bash
pytest tests/analysis/test_dedup_pipeline.py -v
```
Expected: `ImportError`

### Step 3: Create the package and types

```python
# lumina/analysis/dedup/__init__.py
"""Layered duplicate detection pipeline."""
```

```python
# lumina/analysis/dedup/types.py
"""Shared types for the deduplication pipeline."""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class CandidatePair:
    """A potential duplicate pair produced by a detection layer."""

    image_id_a: str   # always lex-smaller
    image_id_b: str   # always lex-larger
    layer: str
    confidence: float
    detection_meta: Dict[str, Any]
    verify_carefully: bool = False
    verify_reason: str = ""

    def __post_init__(self) -> None:
        # Enforce canonical ordering so (a,b) == (b,a)
        if self.image_id_a > self.image_id_b:
            self.image_id_a, self.image_id_b = self.image_id_b, self.image_id_a
```

```python
# lumina/analysis/dedup/layers/__init__.py
```

### Step 4: Create L1 and L2 layers

```python
# lumina/analysis/dedup/layers/l1_exact.py
"""L1: Exact duplicate detection via checksum match."""

from collections import defaultdict
from typing import Any, Dict, Iterable, Iterator, List

from ..types import CandidatePair


def detect_exact(images: List[Dict[str, Any]]) -> Iterator[CandidatePair]:
    """Yield pairs with identical checksums.

    Args:
        images: List of dicts with keys: id, checksum, source_path, created_at
    """
    by_checksum: Dict[str, List[Dict]] = defaultdict(list)
    for img in images:
        if img.get("checksum"):
            by_checksum[img["checksum"]].append(img)

    for checksum, group in by_checksum.items():
        if len(group) < 2:
            continue
        # Yield all pairs within the group
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                yield CandidatePair(
                    image_id_a=a["id"],
                    image_id_b=b["id"],
                    layer="exact",
                    confidence=1.0,
                    detection_meta={
                        "checksum": checksum,
                        "path_a": a["source_path"],
                        "path_b": b["source_path"],
                    },
                )
```

```python
# lumina/analysis/dedup/layers/l2_reimport.py
"""L2: Re-import detection via source_path match."""

from collections import defaultdict
from typing import Any, Dict, Iterator, List

from ..types import CandidatePair


def detect_reimport(images: List[Dict[str, Any]]) -> Iterator[CandidatePair]:
    """Yield pairs sharing the same source_path.

    Args:
        images: List of dicts with keys: id, checksum, source_path, created_at
    """
    by_path: Dict[str, List[Dict]] = defaultdict(list)
    for img in images:
        if img.get("source_path"):
            by_path[img["source_path"]].append(img)

    for path, group in by_path.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                yield CandidatePair(
                    image_id_a=a["id"],
                    image_id_b=b["id"],
                    layer="reimport",
                    confidence=1.0,
                    detection_meta={
                        "source_path": path,
                        "created_at_a": str(a.get("created_at", "")),
                        "created_at_b": str(b.get("created_at", "")),
                    },
                )
```

### Step 5: Create pipeline orchestrator

```python
# lumina/analysis/dedup/pipeline.py
"""Pipeline orchestrator: runs layers, checks suppression, upserts candidates."""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Iterator, List, Set, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import text

from .types import CandidatePair

logger = logging.getLogger(__name__)


def load_suppression_set(catalog_id: str, session: Session) -> Set[Tuple[str, str]]:
    """Load all suppressed pairs as a set of (id_a, id_b) tuples."""
    rows = session.execute(
        text("""
            SELECT sp.id_a, sp.id_b
            FROM suppression_pairs sp
            JOIN images i_a ON i_a.id = sp.id_a
            JOIN images i_b ON i_b.id = sp.id_b
            WHERE i_a.catalog_id = :cid OR i_b.catalog_id = :cid
        """),
        {"cid": catalog_id},
    ).fetchall()
    return {(row.id_a, row.id_b) for row in rows}


def filter_suppressed(
    candidates: Iterator[CandidatePair],
    suppressed: Set[Tuple[str, str]],
) -> Iterator[CandidatePair]:
    """Filter out already-reviewed pairs."""
    for c in candidates:
        pair = (min(c.image_id_a, c.image_id_b), max(c.image_id_a, c.image_id_b))
        if pair not in suppressed:
            yield c


def upsert_candidate(candidate: CandidatePair, session: Session) -> None:
    """Insert or refresh a candidate pair (idempotent on pair+layer)."""
    session.execute(
        text("""
            INSERT INTO duplicate_candidates
                (id, catalog_id, image_id_a, image_id_b, layer, confidence,
                 verify_carefully, verify_reason, detection_meta, created_at)
            SELECT
                gen_random_uuid(),
                i.catalog_id,
                :a, :b, :layer, :confidence,
                :verify_carefully, :verify_reason, :meta::jsonb, NOW()
            FROM images i WHERE i.id = :a
            ON CONFLICT (image_id_a, image_id_b, layer)
            DO UPDATE SET
                confidence = EXCLUDED.confidence,
                verify_carefully = EXCLUDED.verify_carefully,
                verify_reason = EXCLUDED.verify_reason,
                detection_meta = EXCLUDED.detection_meta
        """),
        {
            "a": candidate.image_id_a,
            "b": candidate.image_id_b,
            "layer": candidate.layer,
            "confidence": candidate.confidence,
            "verify_carefully": candidate.verify_carefully,
            "verify_reason": candidate.verify_reason or "",
            "meta": __import__("json").dumps(candidate.detection_meta),
        },
    )
```

### Step 6: Run tests
```bash
pytest tests/analysis/test_dedup_pipeline.py -v
```
Expected: all `PASSED`

### Step 7: Commit
```bash
git add lumina/analysis/dedup/ tests/analysis/test_dedup_pipeline.py
git commit -m "feat: detection pipeline foundation, L1 exact, L2 reimport"
```

---

## Task 5: L3 — Format Variant Detection

**Files:**
- Create: `lumina/analysis/dedup/layers/l3_format_variant.py`
- Test: `tests/analysis/test_dedup_pipeline.py` (extend)

### Step 1: Write failing test

Add to `tests/analysis/test_dedup_pipeline.py`:
```python
def test_l3_format_variant_groups_by_time_and_camera():
    from lumina.analysis.dedup.layers.l3_format_variant import detect_format_variants
    from datetime import datetime
    images = [
        {"id": "raw-1", "format": "raw", "dhash": "a" * 16, "capture_time": datetime(2024,1,1,12,0,0), "camera_make": "Canon", "camera_model": "R5"},
        {"id": "jpg-1", "format": "jpeg", "dhash": "a" * 16, "capture_time": datetime(2024,1,1,12,0,0), "camera_make": "Canon", "camera_model": "R5"},
        {"id": "raw-2", "format": "raw", "dhash": "b" * 16, "capture_time": datetime(2024,1,1,12,0,5), "camera_make": "Canon", "camera_model": "R5"},
    ]
    pairs = list(detect_format_variants(images, threshold=4))
    assert len(pairs) == 1
    assert pairs[0].layer == "format_variant"
    ids = {pairs[0].image_id_a, pairs[0].image_id_b}
    assert ids == {"raw-1", "jpg-1"}

def test_l3_skips_same_format():
    from lumina.analysis.dedup.layers.l3_format_variant import detect_format_variants
    from datetime import datetime
    images = [
        {"id": "jpg-1", "format": "jpeg", "dhash": "a" * 16, "capture_time": datetime(2024,1,1,12,0,0), "camera_make": "Canon", "camera_model": "R5"},
        {"id": "jpg-2", "format": "jpeg", "dhash": "a" * 16, "capture_time": datetime(2024,1,1,12,0,0), "camera_make": "Canon", "camera_model": "R5"},
    ]
    # Same format — should not flag as format_variant (that's L1/L5's job)
    pairs = list(detect_format_variants(images, threshold=4))
    assert len(pairs) == 0
```

### Step 2: Run to confirm failure
```bash
pytest tests/analysis/test_dedup_pipeline.py::test_l3_format_variant_groups_by_time_and_camera -v
```
Expected: `ImportError`

### Step 3: Implement L3

```python
# lumina/analysis/dedup/layers/l3_format_variant.py
"""L3: Format variant detection — same shot, different file format."""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from lumina.analysis.hashing import hamming_distance
from ..types import CandidatePair

RAW_FORMATS = {"raw", "arw", "cr2", "cr3", "nef", "dng", "orf", "rw2", "raf", "pef"}


def _time_bucket(capture_time: Optional[datetime]) -> Optional[str]:
    """Floor capture_time to the nearest second as a string key."""
    if not capture_time:
        return None
    return capture_time.strftime("%Y%m%d%H%M%S")


def detect_format_variants(
    images: List[Dict[str, Any]],
    threshold: float = 4.0,
) -> Iterator[CandidatePair]:
    """Yield pairs that are the same shot in different formats.

    Groups by (capture_time_second, camera_make, camera_model).
    Within each group, only yields pairs where the formats differ.
    Confirms visual identity with dhash Hamming distance.

    Args:
        images: List of dicts with keys: id, format, dhash, capture_time,
                camera_make, camera_model
        threshold: Maximum Hamming distance for dhash match (default 4)
    """
    # Group by (time_bucket, camera_make, camera_model)
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for img in images:
        bucket = _time_bucket(img.get("capture_time"))
        make = img.get("camera_make") or ""
        model = img.get("camera_model") or ""
        if bucket and (make or model):
            key = f"{bucket}|{make}|{model}"
            groups[key].append(img)

    for key, group in groups.items():
        if len(group) < 2:
            continue
        # Only process groups with multiple distinct formats
        formats = {(img.get("format") or "").lower() for img in group}
        if len(formats) < 2:
            continue

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                fmt_a = (a.get("format") or "").lower()
                fmt_b = (b.get("format") or "").lower()
                if fmt_a == fmt_b:
                    continue  # same format — not a format variant

                hash_a = a.get("dhash") or ""
                hash_b = b.get("dhash") or ""
                if not hash_a or not hash_b or len(hash_a) != len(hash_b):
                    continue

                dist = hamming_distance(hash_a, hash_b)
                if dist > threshold:
                    continue

                # Put RAW as image_id_a (the original) when possible
                if fmt_b in RAW_FORMATS and fmt_a not in RAW_FORMATS:
                    a, b = b, a

                confidence = 1.0 - dist / (len(hash_a) * 4)
                yield CandidatePair(
                    image_id_a=a["id"],
                    image_id_b=b["id"],
                    layer="format_variant",
                    confidence=confidence,
                    detection_meta={
                        "hamming": dist,
                        "format_a": (a.get("format") or "").lower(),
                        "format_b": (b.get("format") or "").lower(),
                        "capture_time": str(a.get("capture_time")),
                    },
                )
```

### Step 4: Run tests
```bash
pytest tests/analysis/test_dedup_pipeline.py -v -k "l3"
```
Expected: both `PASSED`

### Step 5: Commit
```bash
git add lumina/analysis/dedup/layers/l3_format_variant.py tests/analysis/test_dedup_pipeline.py
git commit -m "feat: L3 format variant detection (RAW+JPEG, cross-format grouping)"
```

---

## Task 6: Archive Write Path + Decide Endpoint

**Files:**
- Create: `lumina/analysis/dedup/archive.py`
- Create: `lumina/api/routers/duplicates.py`
- Modify: `lumina/api/app.py`
- Test: `tests/api/test_duplicates_api.py`

### Step 1: Write failing API test

```python
# tests/api/test_duplicates_api.py
def test_decide_endpoint_exists(client):
    """The decide endpoint must exist (returns 422 without body, not 404)."""
    r = client.post("/api/catalogs/00000000-0000-0000-0000-000000000000/duplicates/candidates/00000000-0000-0000-0000-000000000001/decide")
    assert r.status_code != 404  # 422 = found but bad input is fine

def test_candidates_list_endpoint_exists(client):
    r = client.get("/api/catalogs/00000000-0000-0000-0000-000000000000/duplicates/candidates")
    assert r.status_code in (200, 404)  # 200 = empty list, 404 = catalog not found
```

### Step 2: Run to confirm failure
```bash
pytest tests/api/test_duplicates_api.py -v
```
Expected: `404` on both (router not mounted)

### Step 3: Create archive module

```python
# lumina/analysis/dedup/archive.py
"""Atomic archive operation: copies image row to archived_images with provenance."""

import logging
from typing import Any, Dict
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def archive_image(
    image_id: str,
    decision_id: str,
    archive_reason: str,
    primary_image_id: str,
    session: Session,
) -> None:
    """Copy an image row to archived_images and set its status to 'archived'.

    Args:
        image_id: The image to archive
        decision_id: The duplicate_decisions row that authorised this
        archive_reason: The detection layer name (exact, reimport, etc.)
        primary_image_id: The image that survives (kept in catalog)
        session: Active SQLAlchemy session
    """
    # Copy row to archived_images
    session.execute(
        text("""
            INSERT INTO archived_images (
                id, catalog_id, source_path, file_type, checksum, size_bytes,
                dates, metadata, thumbnail_path,
                dhash, ahash, whash, dhash_16, dhash_32,
                quality_score, capture_time, camera_make, camera_model,
                width, height, format, latitude, longitude,
                processing_flags, created_at,
                archived_at, archive_reason, decision_id,
                primary_image_id, original_catalog_id, restoration_path
            )
            SELECT
                id, catalog_id, source_path, file_type, checksum, size_bytes,
                dates, metadata, thumbnail_path,
                dhash, ahash, whash, dhash_16, dhash_32,
                quality_score, capture_time, camera_make, camera_model,
                width, height, format, latitude, longitude,
                processing_flags, created_at,
                NOW(), :reason, :decision_id::uuid,
                :primary_id, catalog_id, source_path
            FROM images WHERE id = :image_id
            ON CONFLICT (id) DO NOTHING
        """),
        {
            "image_id": image_id,
            "reason": archive_reason,
            "decision_id": decision_id,
            "primary_id": primary_image_id,
        },
    )

    # Set image status to archived
    session.execute(
        text("UPDATE images SET status_id = 'archived' WHERE id = :id"),
        {"id": image_id},
    )
    logger.info(f"Archived image {image_id} (reason={archive_reason}, kept={primary_image_id})")


def restore_image(archived_id: str, session: Session) -> None:
    """Restore an archived image back to active status."""
    session.execute(
        text("UPDATE images SET status_id = 'active' WHERE id = :id"),
        {"id": archived_id},
    )
    session.execute(
        text("DELETE FROM archived_images WHERE id = :id"),
        {"id": archived_id},
    )
    logger.info(f"Restored archived image {archived_id}")
```

### Step 4: Ensure 'archived' status exists in image_statuses

```bash
python -c "
from lumina.db.connection import SessionLocal
from sqlalchemy import text
with SessionLocal() as s:
    s.execute(text(\"INSERT INTO image_statuses (id, name, description) VALUES ('archived', 'Archived', 'Duplicate archived with provenance') ON CONFLICT DO NOTHING\"))
    s.commit()
    print('archived status ensured')
"
```

### Step 5: Create duplicates router

```python
# lumina/api/routers/duplicates.py
"""Duplicate detection review queue and decision endpoints."""

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...db import get_db
from ..routers.catalogs import get_catalog_or_404

logger = logging.getLogger(__name__)
router = APIRouter()


class DecideRequest(BaseModel):
    decision: str   # confirmed_duplicate | not_duplicate | deferred
    primary_id: Optional[str] = None
    notes: Optional[str] = None


@router.get("/{catalog_id}/duplicates/candidates")
def list_candidates(
    catalog_id: uuid.UUID,
    layer: Optional[str] = None,
    min_confidence: float = 0.0,
    verify_carefully: Optional[bool] = None,
    reviewed: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    get_catalog_or_404(catalog_id, db)

    filters = ["dc.catalog_id = :cid"]
    params: Dict[str, Any] = {"cid": str(catalog_id), "limit": limit, "offset": offset}

    if layer:
        filters.append("dc.layer = :layer")
        params["layer"] = layer
    if min_confidence > 0:
        filters.append("dc.confidence >= :min_conf")
        params["min_conf"] = min_confidence
    if verify_carefully is not None:
        filters.append("dc.verify_carefully = :vc")
        params["vc"] = verify_carefully
    if not reviewed:
        filters.append("dc.reviewed_at IS NULL")
    else:
        filters.append("dc.reviewed_at IS NOT NULL")

    where = " AND ".join(filters)
    rows = db.execute(
        text(f"""
            SELECT dc.*, 
                   ia.source_path as path_a, ia.width as w_a, ia.height as h_a, ia.format as fmt_a,
                   ib.source_path as path_b, ib.width as w_b, ib.height as h_b, ib.format as fmt_b
            FROM duplicate_candidates dc
            JOIN images ia ON ia.id = dc.image_id_a
            JOIN images ib ON ib.id = dc.image_id_b
            WHERE {where}
            ORDER BY dc.verify_carefully DESC, dc.confidence DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).fetchall()

    total = db.execute(
        text(f"SELECT COUNT(*) FROM duplicate_candidates dc WHERE {where}"),
        params,
    ).scalar()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "candidates": [dict(row._mapping) for row in rows],
    }


@router.get("/{catalog_id}/duplicates/candidates/{candidate_id}")
def get_candidate(
    catalog_id: uuid.UUID,
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    get_catalog_or_404(catalog_id, db)
    row = db.execute(
        text("SELECT * FROM duplicate_candidates WHERE id = :id AND catalog_id = :cid"),
        {"id": str(candidate_id), "cid": str(catalog_id)},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return dict(row._mapping)


@router.post("/{catalog_id}/duplicates/candidates/{candidate_id}/decide")
def decide_candidate(
    catalog_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: DecideRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Atomic decision: write decision, suppress pair, archive if confirmed."""
    if body.decision not in ("confirmed_duplicate", "not_duplicate", "deferred"):
        raise HTTPException(status_code=422, detail="Invalid decision value")
    if body.decision == "confirmed_duplicate" and not body.primary_id:
        raise HTTPException(status_code=422, detail="primary_id required for confirmed_duplicate")

    get_catalog_or_404(catalog_id, db)

    candidate = db.execute(
        text("SELECT * FROM duplicate_candidates WHERE id = :id AND catalog_id = :cid"),
        {"id": str(candidate_id), "cid": str(catalog_id)},
    ).fetchone()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # 1. Write decision
    decision_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO duplicate_decisions (id, candidate_id, decision, primary_id, notes, decided_at)
            VALUES (:id, :cid, :decision, :primary_id, :notes, NOW())
        """),
        {
            "id": decision_id,
            "cid": str(candidate_id),
            "decision": body.decision,
            "primary_id": body.primary_id,
            "notes": body.notes,
        },
    )

    # 2. Mark candidate as reviewed
    db.execute(
        text("UPDATE duplicate_candidates SET reviewed_at = NOW() WHERE id = :id"),
        {"id": str(candidate_id)},
    )

    # 3. Suppress pair
    id_a = min(candidate.image_id_a, candidate.image_id_b)
    id_b = max(candidate.image_id_a, candidate.image_id_b)
    db.execute(
        text("""
            INSERT INTO suppression_pairs (id_a, id_b, decision, created_at)
            VALUES (:a, :b, :decision, NOW())
            ON CONFLICT (id_a, id_b) DO NOTHING
        """),
        {"a": id_a, "b": id_b, "decision": body.decision},
    )

    # 4. Archive if confirmed
    if body.decision == "confirmed_duplicate":
        archive_id = candidate.image_id_b if candidate.image_id_b != body.primary_id else candidate.image_id_a
        from ...analysis.dedup.archive import archive_image
        archive_image(
            image_id=archive_id,
            decision_id=decision_id,
            archive_reason=candidate.layer,
            primary_image_id=body.primary_id,
            session=db,
        )

    # 5. Update threshold (async-safe: fire and forget in same transaction)
    if body.decision != "deferred":
        _update_threshold(str(catalog_id), candidate.layer, candidate.detection_meta, body.decision, db)

    db.commit()
    return {"decision_id": decision_id, "status": "recorded"}


def _update_threshold(
    catalog_id: str,
    layer: str,
    detection_meta: Dict,
    decision: str,
    db: Session,
) -> None:
    """EMA threshold adaptation from user decision."""
    ALPHA = 0.15
    LAYER_BOUNDS = {
        "format_variant": (0.0, 4.0),
        "preview": (1.0, 6.0),
        "near_duplicate": (2.0, 12.0),
    }
    if layer not in LAYER_BOUNDS:
        return

    hamming = detection_meta.get("hamming")
    if hamming is None:
        return

    row = db.execute(
        text("SELECT * FROM detection_thresholds WHERE catalog_id = :cid AND layer = :layer"),
        {"cid": catalog_id, "layer": layer},
    ).fetchone()
    if not row:
        return

    target = (hamming + 1) if decision == "confirmed_duplicate" else (hamming - 1)
    lo, hi = LAYER_BOUNDS[layer]
    new_threshold = max(lo, min(hi, row.threshold * (1 - ALPHA) + target * ALPHA))

    db.execute(
        text("""
            UPDATE detection_thresholds
            SET threshold = :t,
                confirmed_count = confirmed_count + :conf,
                rejected_count = rejected_count + :rej,
                last_updated = NOW()
            WHERE catalog_id = :cid AND layer = :layer
        """),
        {
            "t": new_threshold,
            "conf": 1 if decision == "confirmed_duplicate" else 0,
            "rej": 1 if decision == "not_duplicate" else 0,
            "cid": catalog_id,
            "layer": layer,
        },
    )


@router.get("/{catalog_id}/duplicates/stats")
def get_duplicate_stats(
    catalog_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    get_catalog_or_404(catalog_id, db)
    rows = db.execute(
        text("""
            SELECT layer,
                   COUNT(*) FILTER (WHERE reviewed_at IS NULL) as pending,
                   COUNT(*) FILTER (WHERE reviewed_at IS NOT NULL) as reviewed,
                   AVG(confidence) as avg_confidence,
                   COUNT(*) FILTER (WHERE verify_carefully AND reviewed_at IS NULL) as verify_carefully_pending
            FROM duplicate_candidates
            WHERE catalog_id = :cid
            GROUP BY layer
        """),
        {"cid": str(catalog_id)},
    ).fetchall()

    thresholds = db.execute(
        text("SELECT layer, threshold, confirmed_count, rejected_count FROM detection_thresholds WHERE catalog_id = :cid"),
        {"cid": str(catalog_id)},
    ).fetchall()

    suppressed = db.execute(
        text("""
            SELECT COUNT(*) FROM suppression_pairs sp
            JOIN images i ON i.id = sp.id_a
            WHERE i.catalog_id = :cid
        """),
        {"cid": str(catalog_id)},
    ).scalar()

    return {
        "by_layer": [dict(r._mapping) for r in rows],
        "thresholds": [dict(r._mapping) for r in thresholds],
        "suppressed_pairs": suppressed,
    }


@router.get("/{catalog_id}/duplicates/thresholds")
def get_thresholds(catalog_id: uuid.UUID, db: Session = Depends(get_db)) -> List[Dict]:
    get_catalog_or_404(catalog_id, db)
    rows = db.execute(
        text("SELECT * FROM detection_thresholds WHERE catalog_id = :cid"),
        {"cid": str(catalog_id)},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


@router.put("/{catalog_id}/duplicates/thresholds/{layer}")
def override_threshold(
    catalog_id: uuid.UUID,
    layer: str,
    body: Dict[str, float],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    get_catalog_or_404(catalog_id, db)
    new_val = body.get("threshold")
    if new_val is None:
        raise HTTPException(status_code=422, detail="threshold field required")
    db.execute(
        text("""
            UPDATE detection_thresholds
            SET threshold = :t, confirmed_count = 0, rejected_count = 0, last_updated = NOW()
            WHERE catalog_id = :cid AND layer = :layer
        """),
        {"t": new_val, "cid": str(catalog_id), "layer": layer},
    )
    db.commit()
    return {"layer": layer, "threshold": new_val}


@router.get("/{catalog_id}/archive")
def list_archive(
    catalog_id: uuid.UUID,
    reason: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    get_catalog_or_404(catalog_id, db)
    filters = ["original_catalog_id = :cid"]
    params: Dict[str, Any] = {"cid": str(catalog_id), "limit": limit, "offset": offset}
    if reason:
        filters.append("archive_reason = :reason")
        params["reason"] = reason
    where = " AND ".join(filters)
    rows = db.execute(
        text(f"SELECT * FROM archived_images WHERE {where} ORDER BY archived_at DESC LIMIT :limit OFFSET :offset"),
        params,
    ).fetchall()
    total = db.execute(text(f"SELECT COUNT(*) FROM archived_images WHERE {where}"), params).scalar()
    return {"total": total, "items": [dict(r._mapping) for r in rows]}


@router.post("/{catalog_id}/archive/{archived_id}/restore")
def restore_archived(
    catalog_id: uuid.UUID,
    archived_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    get_catalog_or_404(catalog_id, db)
    from ...analysis.dedup.archive import restore_image
    restore_image(archived_id, db)
    db.commit()
    return {"restored": archived_id}
```

### Step 6: Mount router in `lumina/api/app.py`

Add after the existing router imports:
```python
from .routers import duplicates
```

Add after existing `app.include_router` calls:
```python
app.include_router(duplicates.router, prefix="/api/catalogs", tags=["duplicates"])
```

### Step 7: Run tests
```bash
pytest tests/api/test_duplicates_api.py -v
```
Expected: both `PASSED`

### Step 8: Smoke test the live API
```bash
curl -s http://localhost:8765/api/catalogs/36ee8b6f-9bfc-4bcd-a0ad-3e5a26946886/duplicates/stats | python3 -m json.tool
```
Expected: JSON with `by_layer` and `thresholds` arrays (empty but valid)

### Step 9: Commit
```bash
git add lumina/analysis/dedup/archive.py lumina/api/routers/duplicates.py lumina/api/app.py tests/api/test_duplicates_api.py
git commit -m "feat: archive write path and duplicate review API (decide, list, stats, restore)"
```

---

## Task 7: L4 — Preview Detection

**Files:**
- Create: `lumina/analysis/dedup/layers/l4_preview.py`
- Test: `tests/analysis/test_dedup_pipeline.py` (extend)

### Step 1: Write failing tests

Add to `tests/analysis/test_dedup_pipeline.py`:
```python
def test_l4_preview_detects_scaled_image(tmp_path):
    """A half-size copy of an image should be flagged as preview."""
    from PIL import Image as PILImage
    from lumina.analysis.hashing import compute_dhash
    from lumina.analysis.dedup.layers.l4_preview import detect_previews
    from datetime import datetime

    # Create a 1000x1000 "original"
    orig_path = tmp_path / "original.jpg"
    PILImage.new("RGB", (1000, 1000), color=(100, 150, 200)).save(orig_path)

    # Create a 200x200 "preview" of same content
    preview_path = tmp_path / "Previews" / "original_preview.jpg"
    preview_path.parent.mkdir()
    PILImage.new("RGB", (200, 200), color=(100, 150, 200)).save(preview_path)

    images = [
        {
            "id": "orig", "source_path": str(orig_path), "width": 1000, "height": 1000,
            "format": "jpeg", "dhash": compute_dhash(orig_path, 8),
            "dhash_16": compute_dhash(orig_path, 16), "dhash_32": compute_dhash(orig_path, 32),
            "created_at": datetime(2024, 1, 1), "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
        {
            "id": "prev", "source_path": str(preview_path), "width": 200, "height": 200,
            "format": "jpeg", "dhash": compute_dhash(preview_path, 8),
            "dhash_16": compute_dhash(preview_path, 16), "dhash_32": compute_dhash(preview_path, 32),
            "created_at": datetime(2024, 6, 1), "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
    ]
    pairs = list(detect_previews(images, threshold=6))
    assert len(pairs) == 1
    assert pairs[0].layer == "preview"
    assert pairs[0].image_id_a == "orig"  # larger image is image_id_a

def test_l4_small_image_requires_corroboration(tmp_path):
    """Image <1MP without corroborating signals must NOT produce a candidate."""
    from PIL import Image as PILImage
    from lumina.analysis.hashing import compute_dhash
    from lumina.analysis.dedup.layers.l4_preview import detect_previews
    from datetime import datetime

    orig_path = tmp_path / "original.jpg"
    PILImage.new("RGB", (2000, 1000), color=(50, 100, 150)).save(orig_path)

    small_path = tmp_path / "small_unknown.jpg"  # no preview path signal
    PILImage.new("RGB", (500, 250), color=(50, 100, 150)).save(small_path)

    images = [
        {
            "id": "orig", "source_path": str(orig_path), "width": 2000, "height": 1000,
            "format": "jpeg", "dhash": compute_dhash(orig_path, 8),
            "dhash_16": compute_dhash(orig_path, 16), "dhash_32": compute_dhash(orig_path, 32),
            "created_at": datetime(2024, 1, 1), "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
        {
            "id": "small", "source_path": str(small_path), "width": 500, "height": 250,
            "format": "jpeg", "dhash": compute_dhash(small_path, 8),
            "dhash_16": compute_dhash(small_path, 16), "dhash_32": compute_dhash(small_path, 32),
            "created_at": datetime(2024, 1, 1), "capture_time": datetime(2024, 1, 1),
            "metadata_json": {},
        },
    ]
    pairs = list(detect_previews(images, threshold=6))
    # 500*250 = 125,000 < 1MP, no path signals, only 0 corroboration → skip
    assert len(pairs) == 0
```

### Step 2: Run to confirm failure
```bash
pytest tests/analysis/test_dedup_pipeline.py -k "l4" -v
```
Expected: `ImportError`

### Step 3: Implement L4

```python
# lumina/analysis/dedup/layers/l4_preview.py
"""L4: Preview/derivative detection via scale-invariant perceptual hash."""

import re
from datetime import datetime, timedelta
from math import sqrt
from typing import Any, Dict, Iterator, List, Optional

from lumina.analysis.hashing import hamming_distance
from ..types import CandidatePair

SMALL_IMAGE_PIXELS = 1_000_000  # 1MP safety threshold

PREVIEW_PATH_PATTERNS = [
    "/Previews/", "/.lrdata/", "/cache/", "/Cache/", "/Thumbs/",
    "/Lightroom/", "/.thumbnails/", "/proxies/", "/Proxies/",
]
PREVIEW_EXTENSIONS = {".lrprev"}
PREVIEW_NAME_RE = re.compile(r"_(preview|thumb|sm|proxy|low|web)\b", re.I)
RAW_FORMATS = {"raw", "arw", "cr2", "cr3", "nef", "dng", "orf", "rw2", "raf", "pef"}


def _count_corroborating_signals(small: Dict, large: Dict) -> int:
    path = small.get("source_path") or ""
    signals = 0

    if any(p in path for p in PREVIEW_PATH_PATTERNS):
        signals += 1
    if any(path.endswith(ext) for ext in PREVIEW_EXTENSIONS):
        signals += 1
    if PREVIEW_NAME_RE.search(path):
        signals += 1

    # EXIF stripped or capture_time mismatch
    if small.get("metadata_json", {}).get("exif_stripped"):
        signals += 1
    if small.get("capture_time") and large.get("capture_time"):
        if small["capture_time"] != large["capture_time"]:
            signals += 1

    # File created significantly after capture (likely an export)
    if small.get("created_at") and large.get("capture_time"):
        try:
            if small["created_at"] > large["capture_time"] + timedelta(minutes=5):
                signals += 1
        except TypeError:
            pass

    # Large is RAW, small is JPEG
    large_fmt = (large.get("format") or "").lower()
    small_fmt = (small.get("format") or "").lower()
    if large_fmt in RAW_FORMATS and small_fmt == "jpeg":
        signals += 1

    return signals


def _size_band_candidates(
    large: Dict,
    all_images: List[Dict],
    min_ratio: float = 0.05,
    max_ratio: float = 0.95,
) -> Iterator[Dict]:
    """Yield images smaller than large within the size ratio band."""
    large_pixels = (large.get("width") or 0) * (large.get("height") or 0)
    if large_pixels == 0:
        return
    for img in all_images:
        if img["id"] == large["id"]:
            continue
        small_pixels = (img.get("width") or 0) * (img.get("height") or 0)
        if small_pixels == 0:
            continue
        ratio = small_pixels / large_pixels
        if min_ratio <= ratio <= max_ratio:
            yield img


def detect_previews(
    images: List[Dict[str, Any]],
    threshold: float = 3.0,
) -> Iterator[CandidatePair]:
    """Yield pairs where a smaller image is likely a preview of a larger one.

    Uses scale-aware hash comparison:
    - scale > 0.5  → compare dhash_16 (256-bit)
    - scale > 0.25 → compare dhash_8  (64-bit)
    - scale ≤ 0.25 → skip (too small to hash reliably)

    Small images (<1MP) require ≥2 corroborating signals and are
    hard-capped at 0.65 confidence with verify_carefully=True.
    """
    # Sort largest-first so we compare small against their likely originals
    by_size = sorted(
        images,
        key=lambda i: (i.get("width") or 0) * (i.get("height") or 0),
        reverse=True,
    )

    for large in by_size:
        large_pixels = (large.get("width") or 0) * (large.get("height") or 0)
        if large_pixels < SMALL_IMAGE_PIXELS:
            break  # remaining images are all small — no more large originals

        for small in _size_band_candidates(large, images):
            small_pixels = (small.get("width") or 0) * (small.get("height") or 0)
            scale = sqrt(small_pixels / large_pixels)

            # Choose hash resolution by scale
            if scale > 0.5:
                hash_large = large.get("dhash_16") or ""
                hash_small = small.get("dhash_16") or ""
                hash_bits = 256
            elif scale > 0.25:
                hash_large = large.get("dhash") or ""
                hash_small = small.get("dhash") or ""
                hash_bits = 64
            else:
                continue  # too small

            if not hash_large or not hash_small or len(hash_large) != len(hash_small):
                continue

            dist = hamming_distance(hash_large, hash_small)
            if dist > threshold:
                continue

            corroboration = _count_corroborating_signals(small, large)
            base_confidence = 1.0 - dist / hash_bits

            if small_pixels < SMALL_IMAGE_PIXELS:
                if corroboration < 2:
                    continue
                confidence = min(base_confidence, 0.65)
                verify_carefully = True
                verify_reason = (
                    f"Small image ({small_pixels/1e6:.2f}MP) with "
                    f"{corroboration} corroborating signal(s)"
                )
            else:
                confidence = base_confidence
                verify_carefully = False
                verify_reason = ""

            yield CandidatePair(
                image_id_a=large["id"],
                image_id_b=small["id"],
                layer="preview",
                confidence=confidence,
                verify_carefully=verify_carefully,
                verify_reason=verify_reason,
                detection_meta={
                    "scale": round(scale, 3),
                    "hamming": dist,
                    "hash_bits": hash_bits,
                    "corroboration": corroboration,
                    "small_pixels": small_pixels,
                },
            )
```

### Step 4: Run tests
```bash
pytest tests/analysis/test_dedup_pipeline.py -k "l4" -v
```
Expected: both `PASSED`

### Step 5: Commit
```bash
git add lumina/analysis/dedup/layers/l4_preview.py tests/analysis/test_dedup_pipeline.py
git commit -m "feat: L4 preview detection with scale-invariant hashing and small-image safety"
```

---

## Task 8: L5 — Near Duplicate Detection with BK-Tree

**Files:**
- Create: `lumina/analysis/dedup/bktree.py`
- Create: `lumina/analysis/dedup/layers/l5_near_duplicate.py`
- Test: `tests/analysis/test_dedup_pipeline.py` (extend)

### Step 1: Write failing tests

Add to `tests/analysis/test_dedup_pipeline.py`:
```python
def test_bktree_finds_neighbors_within_distance():
    from lumina.analysis.dedup.bktree import BKTree
    from lumina.analysis.hashing import hamming_distance

    items = [("a", "0000000000000000"), ("b", "0000000000000001"), ("c", "ffffffffffffffff")]
    tree = BKTree(hamming_distance, items)
    results = tree.find("0000000000000000", 2)
    ids = {r[0] for r in results}
    assert "a" in ids
    assert "b" in ids
    assert "c" not in ids

def test_l5_near_duplicate_finds_similar():
    from lumina.analysis.dedup.layers.l5_near_duplicate import detect_near_duplicates
    images = [
        {"id": "img-1", "dhash": "0000000000000000"},
        {"id": "img-2", "dhash": "0000000000000001"},  # 1 bit diff
        {"id": "img-3", "dhash": "ffffffffffffffff"},  # totally different
    ]
    pairs = list(detect_near_duplicates(images, threshold=4))
    assert len(pairs) == 1
    assert pairs[0].layer == "near_duplicate"
    ids = {pairs[0].image_id_a, pairs[0].image_id_b}
    assert ids == {"img-1", "img-2"}
```

### Step 2: Run to confirm failure
```bash
pytest tests/analysis/test_dedup_pipeline.py -k "bktree or l5" -v
```
Expected: `ImportError`

### Step 3: Implement BK-tree

```python
# lumina/analysis/dedup/bktree.py
"""Pure Python BK-tree for efficient nearest-neighbor search in metric spaces.

A BK-tree supports queries of the form "find all items within distance d
of query q" in O(n^d) average case — much faster than O(n²) brute force
for low-dimensional metric spaces like Hamming distance over perceptual hashes.
"""

from typing import Any, Callable, Iterable, Iterator, List, Tuple


class BKTree:
    """BK-tree for metric space nearest-neighbor search.

    Args:
        distance_fn: A function (a, b) -> int that satisfies the metric axioms.
        items: Iterable of (id, value) tuples to index.
    """

    def __init__(
        self,
        distance_fn: Callable[[Any, Any], int],
        items: Iterable[Tuple[Any, Any]],
    ) -> None:
        self._dist = distance_fn
        self._root: Any = None  # (id, value, children: dict[int, node])

        for item_id, value in items:
            self._insert(item_id, value)

    def _insert(self, item_id: Any, value: Any) -> None:
        if self._root is None:
            self._root = [item_id, value, {}]
            return
        node = self._root
        while True:
            d = self._dist(value, node[1])
            if d in node[2]:
                node = node[2][d]
            else:
                node[2][d] = [item_id, value, {}]
                break

    def find(self, query: Any, max_distance: int) -> List[Tuple[Any, int]]:
        """Return all (id, distance) pairs within max_distance of query."""
        if self._root is None:
            return []
        results: List[Tuple[Any, int]] = []
        stack = [self._root]
        while stack:
            node = stack.pop()
            d = self._dist(query, node[1])
            if d <= max_distance:
                results.append((node[0], d))
            lo = max(0, d - max_distance)
            hi = d + max_distance
            for dist_key, child in node[2].items():
                if lo <= dist_key <= hi:
                    stack.append(child)
        return results
```

### Step 4: Implement L5

```python
# lumina/analysis/dedup/layers/l5_near_duplicate.py
"""L5: Near-duplicate detection via BK-tree over dhash_8 values."""

from typing import Any, Dict, Iterator, List

from lumina.analysis.hashing import hamming_distance
from ..bktree import BKTree
from ..types import CandidatePair

HASH_BITS = 64  # dhash_8 is 64-bit


def detect_near_duplicates(
    images: List[Dict[str, Any]],
    threshold: float = 8.0,
) -> Iterator[CandidatePair]:
    """Yield near-duplicate pairs within Hamming distance threshold.

    Uses a BK-tree over dhash_8 values for O(n log n) average performance.
    Only images with a valid dhash are indexed.

    Args:
        images: List of dicts with keys: id, dhash
        threshold: Maximum Hamming distance (default 8; adaptive per catalog)
    """
    # Filter to images with valid hashes
    hashable = [(img["id"], img["dhash"]) for img in images if img.get("dhash")]
    if len(hashable) < 2:
        return

    tree = BKTree(hamming_distance, hashable)
    seen: set = set()
    max_dist = int(threshold)

    for img_id, img_hash in hashable:
        for neighbor_id, dist in tree.find(img_hash, max_dist):
            if neighbor_id == img_id:
                continue
            pair_key = (min(img_id, neighbor_id), max(img_id, neighbor_id))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            yield CandidatePair(
                image_id_a=pair_key[0],
                image_id_b=pair_key[1],
                layer="near_duplicate",
                confidence=1.0 - dist / HASH_BITS,
                detection_meta={"hamming": dist},
            )
```

### Step 5: Run tests
```bash
pytest tests/analysis/test_dedup_pipeline.py -k "bktree or l5" -v
```
Expected: both `PASSED`

### Step 6: Commit
```bash
git add lumina/analysis/dedup/bktree.py lumina/analysis/dedup/layers/l5_near_duplicate.py tests/analysis/test_dedup_pipeline.py
git commit -m "feat: BK-tree and L5 near-duplicate detection"
```

---

## Task 9: Detection Job (`detect_duplicates_v2`)

**Files:**
- Create: `lumina/jobs/definitions/detect_duplicates_v2.py`
- Modify: `lumina/jobs/job_implementations.py`
- Test: `tests/jobs/test_detect_duplicates_v2.py`

### Step 1: Write failing test

```python
# tests/jobs/test_detect_duplicates_v2.py
def test_job_registered():
    from lumina.jobs import framework
    import lumina.jobs.definitions.detect_duplicates_v2  # noqa: F401
    assert "detect_duplicates_v2" in framework.job_registry._jobs

def test_reprocess_mode_values():
    from lumina.jobs.definitions.detect_duplicates_v2 import ReprocessMode
    assert ReprocessMode.NEW_IMAGES_ONLY.value == "new"
    assert ReprocessMode.THRESHOLD_CHANGED.value == "layer"
    assert ReprocessMode.FULL_RESCAN.value == "full"
```

### Step 2: Run to confirm failure
```bash
pytest tests/jobs/test_detect_duplicates_v2.py -v
```
Expected: `ImportError`

### Step 3: Implement the job

```python
# lumina/jobs/definitions/detect_duplicates_v2.py
"""Job: detect_duplicates_v2 — runs all 5 detection layers sequentially."""

import logging
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..framework import ParallelJob, register_job
from ...db.connection import SessionLocal
from ...analysis.dedup.pipeline import filter_suppressed, load_suppression_set, upsert_candidate
from ...analysis.dedup.layers.l1_exact import detect_exact
from ...analysis.dedup.layers.l2_reimport import detect_reimport
from ...analysis.dedup.layers.l3_format_variant import detect_format_variants
from ...analysis.dedup.layers.l4_preview import detect_previews
from ...analysis.dedup.layers.l5_near_duplicate import detect_near_duplicates

logger = logging.getLogger(__name__)


class ReprocessMode(Enum):
    NEW_IMAGES_ONLY = "new"
    THRESHOLD_CHANGED = "layer"
    FULL_RESCAN = "full"


DEFAULT_THRESHOLDS = {
    "format_variant": 4.0,
    "preview": 3.0,
    "near_duplicate": 8.0,
}


def _load_images(catalog_id: str, session, mode: str = "new", since_id: Optional[str] = None) -> List[Dict]:
    """Load images from database for detection."""
    base_query = """
        SELECT id, source_path, checksum, format, dhash, ahash, whash,
               dhash_16, dhash_32, width, height, capture_time,
               camera_make, camera_model, created_at, metadata
        FROM images
        WHERE catalog_id = :cid AND status_id = 'active'
    """
    params: Dict[str, Any] = {"cid": catalog_id}

    if mode == "new" and since_id:
        base_query += " AND created_at > (SELECT created_at FROM images WHERE id = :since)"
        params["since"] = since_id

    rows = session.execute(text(base_query), params).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_thresholds(catalog_id: str, session) -> Dict[str, float]:
    rows = session.execute(
        text("SELECT layer, threshold FROM detection_thresholds WHERE catalog_id = :cid"),
        {"cid": catalog_id},
    ).fetchall()
    thresholds = dict(DEFAULT_THRESHOLDS)
    for row in rows:
        thresholds[row.layer] = row.threshold
    return thresholds


def _clear_unreviewed(catalog_id: str, layer: Optional[str], session) -> None:
    """Clear unreviewed candidates (never touches reviewed ones)."""
    params: Dict[str, Any] = {"cid": catalog_id}
    layer_filter = ""
    if layer:
        layer_filter = " AND layer = :layer"
        params["layer"] = layer
    session.execute(
        text(f"""
            DELETE FROM duplicate_candidates
            WHERE catalog_id = :cid AND reviewed_at IS NULL {layer_filter}
        """),
        params,
    )


def discover_catalog(catalog_id: str, **kwargs) -> List[str]:
    """Discovery: returns a single-item list so finalize runs once."""
    return [catalog_id]


def run_all_layers(
    catalog_id: str,
    catalog_id_param: str,
    mode: str = "full",
    layer: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Process: run all detection layers for the catalog."""
    with SessionLocal() as session:
        # Clear stale candidates based on mode
        if mode == "full":
            _clear_unreviewed(catalog_id, None, session)
        elif mode == "layer" and layer:
            _clear_unreviewed(catalog_id, layer, session)
        session.commit()

        images = _load_images(catalog_id, session, mode)
        thresholds = _load_thresholds(catalog_id, session)
        suppressed = load_suppression_set(catalog_id, session)

        counts: Dict[str, int] = {}

        layer_fns = [
            ("exact", lambda imgs, t: detect_exact(imgs)),
            ("reimport", lambda imgs, t: detect_reimport(imgs)),
            ("format_variant", lambda imgs, t: detect_format_variants(imgs, t.get("format_variant", 4.0))),
            ("preview", lambda imgs, t: detect_previews(imgs, t.get("preview", 3.0))),
            ("near_duplicate", lambda imgs, t: detect_near_duplicates(imgs, t.get("near_duplicate", 8.0))),
        ]

        # If targeted layer reprocess, only run that layer
        if mode == "layer" and layer:
            layer_fns = [(name, fn) for name, fn in layer_fns if name == layer]

        for layer_name, layer_fn in layer_fns:
            n = 0
            for candidate in filter_suppressed(layer_fn(images, thresholds), suppressed):
                upsert_candidate(candidate, session)
                n += 1
            session.commit()
            counts[layer_name] = n
            logger.info(f"Layer {layer_name}: {n} candidates")

        # Update last_run_threshold for drift detection
        for lyr, default in DEFAULT_THRESHOLDS.items():
            current = thresholds.get(lyr, default)
            session.execute(
                text("""
                    UPDATE detection_thresholds
                    SET last_run_threshold = :t
                    WHERE catalog_id = :cid AND layer = :layer
                """),
                {"t": current, "cid": catalog_id, "layer": lyr},
            )
        session.commit()

        return {"catalog_id": catalog_id, "mode": mode, "candidates_by_layer": counts}


def finalize_detection(results: List[Dict], catalog_id: str, **kwargs) -> Dict[str, Any]:
    total = sum(
        sum(r.get("candidates_by_layer", {}).values())
        for r in results
    )
    return {"catalog_id": catalog_id, "total_candidates": total, "results": results}


detect_duplicates_v2_job = register_job(
    ParallelJob(
        name="detect_duplicates_v2",
        discover=discover_catalog,
        process=run_all_layers,
        finalize=finalize_detection,
        batch_size=1,
    )
)
```

### Step 4: Register in job_implementations.py

In `lumina/jobs/job_implementations.py`, add to the `JOB_HANDLERS` dict and imports:
```python
from .definitions import detect_duplicates_v2  # noqa: F401
```
And in `JOB_HANDLERS`:
```python
"detect_duplicates_v2": lambda ctx: _run_framework_job(ctx, "detect_duplicates_v2"),
```

### Step 5: Run tests
```bash
pytest tests/jobs/test_detect_duplicates_v2.py -v
```
Expected: both `PASSED`

### Step 6: Smoke test end-to-end on live data
```bash
curl -s -X POST http://localhost:8765/api/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{"job_type": "detect_duplicates_v2", "catalog_id": "36ee8b6f-9bfc-4bcd-a0ad-3e5a26946886", "mode": "full"}' \
  | python3 -m json.tool
```
Note the job ID, then poll:
```bash
JOB_ID=<id from above>
curl -s http://localhost:8765/api/jobs/$JOB_ID | python3 -m json.tool
```

### Step 7: Commit
```bash
git add lumina/jobs/definitions/detect_duplicates_v2.py lumina/jobs/job_implementations.py tests/jobs/test_detect_duplicates_v2.py
git commit -m "feat: detect_duplicates_v2 job with all 5 layers and reprocess modes"
```

---

## Task 10: Warehouse Integration + Reprocess Trigger

**Files:**
- Modify: `lumina/jobs/warehouse_tasks.py` (or `warehouse_scheduler.py`)
- Test: manual verification via stats endpoint

### Step 1: Find where post-scan jobs are triggered

```bash
grep -n "detect_duplicates\|hash_images\|after_scan\|post_scan\|scan_complete" \
  /home/irjudson/Projects/lumina/lumina/jobs/warehouse_scheduler.py \
  /home/irjudson/Projects/lumina/lumina/jobs/warehouse_tasks.py | head -30
```

### Step 2: Add hash_images_v2 and detect_duplicates_v2 to the post-scan pipeline

In whichever file triggers post-scan jobs, add after existing scan completion logic:
```python
# After scan: compute multi-resolution hashes for new images
_submit_job("hash_images_v2", catalog_id, {})

# After hashing: run incremental duplicate detection
_submit_job("detect_duplicates_v2", catalog_id, {"mode": "new"})
```

### Step 3: Add threshold-drift reprocess trigger to the decide endpoint

In `lumina/api/routers/duplicates.py`, after `db.commit()` in `decide_candidate`, add:
```python
# Check if threshold drifted enough to trigger reprocess
_maybe_trigger_reprocess(str(catalog_id), candidate.layer, db)
```

And add the function:
```python
def _maybe_trigger_reprocess(catalog_id: str, layer: str, db: Session) -> None:
    """Submit a targeted reprocess job if threshold drifted ≥ 1 bit."""
    row = db.execute(
        text("""
            SELECT threshold, last_run_threshold FROM detection_thresholds
            WHERE catalog_id = :cid AND layer = :layer
        """),
        {"cid": catalog_id, "layer": layer},
    ).fetchone()
    if row and row.last_run_threshold is not None:
        if abs(row.threshold - row.last_run_threshold) >= 1.0:
            from ...jobs.job_implementations import submit_job
            submit_job("detect_duplicates_v2", catalog_id, {"mode": "layer", "layer": layer})
            logger.info(f"Triggered reprocess for layer {layer} (threshold drift ≥ 1)")
```

### Step 4: Verify stats endpoint shows candidates
```bash
curl -s "http://localhost:8765/api/catalogs/36ee8b6f-9bfc-4bcd-a0ad-3e5a26946886/duplicates/stats" | python3 -m json.tool
```
Expected: `by_layer` array with counts per layer

### Step 5: Commit
```bash
git add lumina/jobs/warehouse_scheduler.py lumina/jobs/warehouse_tasks.py lumina/api/routers/duplicates.py
git commit -m "feat: warehouse integration — auto hash+detect after scan, reprocess on threshold drift"
```

---

## Verification Checklist

Before closing this branch:

- [ ] `pytest tests/db/test_dedup_models.py tests/analysis/test_dedup_pipeline.py tests/jobs/test_hash_v2.py tests/jobs/test_detect_duplicates_v2.py tests/api/test_duplicates_api.py -v` — all pass
- [ ] Migration tables exist in live DB (run Task 2 verify step)
- [ ] `GET /api/catalogs/{id}/duplicates/stats` returns valid JSON
- [ ] `detect_duplicates_v2` job completes via `/api/jobs/submit`
- [ ] `decide` endpoint returns `{"decision_id": ..., "status": "recorded"}` on a real candidate
- [ ] Archived image appears in `GET /api/catalogs/{id}/archive` after confirmed decision
- [ ] `mypy lumina/analysis/dedup/ lumina/jobs/definitions/hash_v2.py lumina/jobs/definitions/detect_duplicates_v2.py` — no errors
