"""SQLAlchemy ORM models for global schema."""

import uuid as uuid_module
from datetime import datetime
from typing import Any, Dict, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()

VALID_LAYERS = {"exact", "reimport", "format_variant", "preview", "near_duplicate"}
VALID_DECISIONS = {"confirmed_duplicate", "not_duplicate", "deferred"}


class Job(Base):
    """Job history in the global (public) schema."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # Job ID
    catalog_id: Mapped[Optional[uuid_module.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # Optional catalog reference
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 'scan' or 'analyze'
    status: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # PENDING, PROGRESS, SUCCESS, FAILURE, etc.
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )  # Job parameters (directories, options, etc.)
    progress: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )  # Progress information (current, total, percent, phase)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )  # Final result when complete
    error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Error message if failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )  # When job completed (success or failure)

    # Warehouse/priority fields
    job_source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="user", server_default="user"
    )  # 'user' or 'warehouse'
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, server_default="50"
    )  # 0-100, higher = more urgent
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )  # When warehouse scheduled this job
    warehouse_trigger: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # What triggered warehouse job

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, type={self.job_type}, status={self.status}, priority={self.priority})>"


class Catalog(Base):
    """Catalog registry in the global (public) schema."""

    __tablename__ = "catalogs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4)
    name = Column(String(255), nullable=False)
    schema_name = Column(String(255), nullable=False, unique=True)
    source_directories = Column(ARRAY(Text), nullable=False)
    organized_directory = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Catalog(id={self.id}, name={self.name}, schema={self.schema_name})>"


class ImageStatus(Base):
    """Status lookup table for images."""

    __tablename__ = "image_statuses"

    id = Column(
        String(50), primary_key=True
    )  # 'active', 'rejected', 'archived', 'flagged'
    name = Column(String(100), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<ImageStatus(id={self.id}, name={self.name})>"


class Image(Base):
    """Image/video records in catalogs."""

    __tablename__ = "images"

    id = Column(String, primary_key=True)  # Unique ID (checksum or UUID)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_path = Column(Text, nullable=False)
    file_type = Column(String, nullable=False)  # 'image' or 'video'
    checksum = Column(Text, nullable=False)
    size_bytes = Column(BigInteger)

    # Dates and metadata stored as JSONB
    dates = Column(JSONB, nullable=False, default={})
    metadata_json = Column("metadata", JSONB, nullable=False, default={})

    # Thumbnail
    thumbnail_path = Column(Text)

    # Perceptual hashes for duplicate detection
    dhash = Column(Text)
    ahash = Column(Text)
    whash = Column(Text)  # Wavelet hash - most robust to transformations
    dhash_16 = Column(Text)  # 256-bit hash for L4 preview detection (scale > 0.5)
    dhash_32 = Column(
        Text
    )  # 1024-bit hash — populated by hash_images_v2, reserved for future use

    # Geohash columns for spatial queries (populated for images with GPS)
    geohash_4 = Column(String(4))  # ~39km precision (country view)
    geohash_6 = Column(String(6))  # ~1.2km precision (city view)
    geohash_8 = Column(String(8))  # ~40m precision (street view)

    # Analysis results
    quality_score = Column(Integer)

    # Queryable metadata columns (extracted from dates/metadata JSONB)
    capture_time = Column(DateTime)
    capture_time_source = Column(String(50))
    date_confidence = Column(Integer)
    camera_make = Column(String(255))
    camera_model = Column(String(255))
    lens_model = Column(String(255))
    width = Column(Integer)
    height = Column(Integer)
    iso = Column(Integer)
    aperture = Column(Float)
    shutter_speed = Column(String(50))
    focal_length = Column(Float)
    latitude = Column(Float)
    longitude = Column(Float)
    gps_altitude = Column(Float)
    orientation = Column(Integer)
    format = Column(String(20))
    metadata_extra = Column(JSONB)

    # Status (references lookup table)
    status_id = Column(
        String(50),
        ForeignKey("image_statuses.id", ondelete="RESTRICT"),
        nullable=False,
        default="active",
        server_default="active",
    )

    # Processing flags - tracks which processing steps are complete
    # Structure: {
    #   "metadata_extracted": bool,  # EXIF/metadata extracted
    #   "dates_extracted": bool,     # Dates parsed with confidence
    #   "thumbnail_generated": bool, # Thumbnail created
    #   "hashes_computed": bool,     # Perceptual hashes computed
    #   "quality_scored": bool,      # Quality analysis complete
    #   "embedding_generated": bool, # CLIP embedding generated
    #   "tags_applied": bool,        # Auto-tagging complete
    #   "description_generated": bool, # Ollama description generated
    #   "ready_for_analysis": bool,  # All required fields for analysis tasks
    # }
    processing_flags = Column(JSONB, nullable=False, default={}, server_default="{}")

    # Burst detection
    burst_id = Column(UUID(as_uuid=True), ForeignKey("bursts.id", ondelete="SET NULL"))
    burst_sequence = Column(Integer)

    # Semantic search
    clip_embedding = Column(Vector(768))  # CLIP embedding for semantic search

    # AI-generated description from Ollama vision model
    description = Column(Text)

    # Non-destructive edit data (transforms, crop, adjustments)
    # Structure: {
    #   "version": 1,
    #   "transforms": {"rotation": 0, "flip_h": false, "flip_v": false},
    #   "crop": null,  # Future: {x, y, width, height}
    #   "adjustments": null,  # Future: {exposure, contrast, saturation}
    # }
    edit_data = Column(JSONB, nullable=True, default=None)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    catalog = relationship("Catalog", backref="images")
    status = relationship("ImageStatus", foreign_keys=[status_id], lazy="joined")
    tags = relationship(
        "ImageTag", back_populates="image", cascade="all, delete-orphan"
    )
    duplicate_memberships = relationship(
        "DuplicateMember", back_populates="image", cascade="all, delete-orphan"
    )
    burst = relationship("Burst", back_populates="images")

    __table_args__ = (
        UniqueConstraint("catalog_id", "checksum", name="unique_catalog_checksum"),
    )

    def __repr__(self) -> str:
        return f"<Image(id={self.id}, path={self.source_path})>"


class Burst(Base):
    """Burst groups of images taken in rapid succession."""

    __tablename__ = "bursts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_count = Column(Integer, nullable=False)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    duration_seconds = Column(Float)
    camera_make = Column(String(255))
    camera_model = Column(String(255))
    best_image_id = Column(String)
    selection_method = Column(String(50), default="quality")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    catalog = relationship("Catalog", backref="bursts")
    images = relationship("Image", back_populates="burst")

    def __repr__(self) -> str:
        return f"<Burst(id={self.id}, image_count={self.image_count}, camera={self.camera_make} {self.camera_model})>"


class Tag(Base):
    """Tags for categorizing images."""

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(Text, nullable=False)
    category = Column(Text)  # Optional category
    parent_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"))
    synonyms = Column(ARRAY(Text))
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    catalog = relationship("Catalog", backref="tags")
    parent = relationship("Tag", remote_side=[id], backref="children")
    images = relationship(
        "ImageTag", back_populates="tag", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("catalog_id", "name", name="unique_catalog_tag"),
    )

    def __repr__(self) -> str:
        return f"<Tag(id={self.id}, name={self.name})>"


class ImageTag(Base):
    """Many-to-many relationship between images and tags."""

    __tablename__ = "image_tags"

    image_id = Column(
        String, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id = Column(
        Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    confidence = Column(Float, default=1.0)  # Combined/final confidence
    source = Column(String, default="manual")  # manual, openclip, ollama, combined
    openclip_confidence = Column(Float, nullable=True)  # Confidence from OpenCLIP
    ollama_confidence = Column(Float, nullable=True)  # Confidence from Ollama
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    image = relationship("Image", back_populates="tags")
    tag = relationship("Tag", back_populates="images")

    def __repr__(self) -> str:
        return f"<ImageTag(image={self.image_id}, tag={self.tag_id}, confidence={self.confidence}, source={self.source})>"


class DuplicateGroup(Base):
    """Groups of duplicate or similar images."""

    __tablename__ = "duplicate_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    primary_image_id = Column(
        String, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    similarity_type = Column(String, nullable=False)  # 'exact' or 'perceptual'
    confidence = Column(Integer, nullable=False)  # 0-100
    reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    catalog = relationship("Catalog", backref="duplicate_groups")
    primary_image = relationship("Image", foreign_keys=[primary_image_id])
    members = relationship(
        "DuplicateMember", back_populates="group", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<DuplicateGroup(id={self.id}, type={self.similarity_type}, confidence={self.confidence})>"


class DuplicateMember(Base):
    """Members of duplicate groups."""

    __tablename__ = "duplicate_members"

    group_id = Column(
        Integer, ForeignKey("duplicate_groups.id", ondelete="CASCADE"), primary_key=True
    )
    image_id = Column(
        String, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True
    )
    similarity_score = Column(Integer, nullable=False)  # 0-100

    # Relationships
    group = relationship("DuplicateGroup", back_populates="members")
    image = relationship("Image", back_populates="duplicate_memberships")

    def __repr__(self) -> str:
        return f"<DuplicateMember(group={self.group_id}, image={self.image_id}, score={self.similarity_score})>"


class Config(Base):
    """Per-catalog configuration settings."""

    __tablename__ = "config"

    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    key = Column(String, primary_key=True)
    value = Column(JSONB, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    catalog = relationship("Catalog", backref="config_entries")

    def __repr__(self) -> str:
        return f"<Config(catalog={self.catalog_id}, key={self.key})>"


class WarehouseConfig(Base):
    """Warehouse automation configuration per catalog."""

    __tablename__ = "warehouse_config"

    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    task_type = Column(String, primary_key=True)
    enabled = Column(Boolean, default=True, nullable=False)
    check_interval_minutes = Column(Integer, default=60, nullable=False)
    threshold = Column(JSONB, default={}, nullable=False)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    catalog = relationship("Catalog", backref="warehouse_config_entries")

    def __repr__(self) -> str:
        return f"<WarehouseConfig(catalog={self.catalog_id}, task={self.task_type}, enabled={self.enabled})>"


class Collection(Base):
    """User-created collections (albums) of images."""

    __tablename__ = "collections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    cover_image_id = Column(
        String, ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    catalog = relationship("Catalog", backref="collections")
    cover_image = relationship("Image", foreign_keys=[cover_image_id])
    collection_images = relationship(
        "CollectionImage", back_populates="collection", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Collection(id={self.id}, name={self.name})>"


class CollectionImage(Base):
    """Many-to-many relationship between collections and images."""

    __tablename__ = "collection_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4)
    collection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_id = Column(
        String, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    position = Column(Integer, default=0)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    collection = relationship("Collection", back_populates="collection_images")
    image = relationship("Image")

    __table_args__ = (
        UniqueConstraint("collection_id", "image_id", name="unique_collection_image"),
    )

    def __repr__(self) -> str:
        return (
            f"<CollectionImage(collection={self.collection_id}, image={self.image_id})>"
        )


class Statistics(Base):
    """Per-catalog statistics tracking."""

    __tablename__ = "statistics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Image counts
    total_images = Column(Integer, default=0)
    total_videos = Column(Integer, default=0)
    total_size_bytes = Column(BigInteger, default=0)
    images_scanned = Column(Integer, default=0)
    images_hashed = Column(Integer, default=0)
    images_tagged = Column(Integer, default=0)

    # Duplicate stats
    duplicate_groups = Column(Integer, default=0)
    duplicate_images = Column(Integer, default=0)
    potential_savings_bytes = Column(BigInteger, default=0)

    # Quality stats
    high_quality_count = Column(Integer, default=0)
    medium_quality_count = Column(Integer, default=0)
    low_quality_count = Column(Integer, default=0)
    corrupted_count = Column(Integer, default=0)
    unsupported_count = Column(Integer, default=0)

    # Performance metrics
    processing_time_seconds = Column(Float, default=0.0)
    images_per_second = Column(Float, default=0.0)

    # Date analysis
    no_date = Column(Integer, default=0)
    suspicious_dates = Column(Integer, default=0)
    problematic_files = Column(Integer, default=0)

    # Relationships
    catalog = relationship("Catalog", backref="statistics")

    def __repr__(self) -> str:
        return f"<Statistics(id={self.id}, catalog={self.catalog_id}, timestamp={self.timestamp})>"


class PerformanceSnapshot(Base):
    """Real-time performance tracking snapshots."""

    __tablename__ = "performance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    phase = Column(Text, nullable=False)  # scanning, hashing, tagging, etc.

    # Progress tracking
    files_processed = Column(Integer, default=0)
    files_total = Column(Integer, default=0)
    bytes_processed = Column(BigInteger, default=0)

    # System metrics
    cpu_percent = Column(Float)
    memory_mb = Column(Float)
    disk_read_mb = Column(Float)
    disk_write_mb = Column(Float)

    # Performance metrics
    elapsed_seconds = Column(Float)
    rate_files_per_sec = Column(Float)
    rate_mb_per_sec = Column(Float)

    # GPU metrics
    gpu_utilization = Column(Float)
    gpu_memory_mb = Column(Float)

    # Relationships
    catalog = relationship("Catalog", backref="performance_snapshots")

    def __repr__(self) -> str:
        return f"<PerformanceSnapshot(id={self.id}, phase={self.phase}, timestamp={self.timestamp})>"


class DuplicateCandidate(Base):
    """Raw output of the duplicate detection pipeline — one row per pair per layer."""

    __tablename__ = "duplicate_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_id_a = Column(
        String, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    image_id_b = Column(
        String, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    layer = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)
    verify_carefully = Column(Boolean, default=False, nullable=False)
    verify_reason = Column(Text)
    detection_meta = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "image_id_a", "image_id_b", "layer", name="uq_candidate_pair_layer"
        ),
        CheckConstraint("image_id_a < image_id_b", name="ck_candidate_pair_ordered"),
        CheckConstraint(
            "layer IN ('exact','reimport','format_variant','preview','near_duplicate')",
            name="ck_candidate_layer",
        ),
    )

    def __repr__(self) -> str:
        return f"<DuplicateCandidate(id={self.id}, layer={self.layer}, confidence={self.confidence})>"


class DuplicateDecision(Base):
    """Immutable audit log of every user decision on a duplicate candidate."""

    __tablename__ = "duplicate_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid_module.uuid4)
    candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("duplicate_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision = Column(String(50), nullable=False)
    primary_id = Column(String, ForeignKey("images.id", ondelete="SET NULL"))
    decided_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "decision IN ('confirmed_duplicate','not_duplicate','deferred')",
            name="ck_decision_value",
        ),
    )

    def __repr__(self) -> str:
        return f"<DuplicateDecision(id={self.id}, decision={self.decision}, candidate_id={self.candidate_id})>"


class ArchivedImage(Base):
    """Full copy of an images row at archive time, with provenance chain."""

    __tablename__ = "archived_images"

    id = Column(Text, primary_key=True)
    catalog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalogs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_path = Column(Text, nullable=False)
    file_type = Column(String, nullable=False)
    checksum = Column(Text, nullable=False)
    size_bytes = Column(BigInteger)
    dates = Column(JSONB, nullable=False, default=dict, server_default="{}")
    metadata_json = Column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
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
    processing_flags = Column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime)
    archived_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    archive_reason = Column(String(50), nullable=False)
    decision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("duplicate_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # No FK — primary image may be deleted; provenance preserved here
    primary_image_id = Column(Text, nullable=False)
    original_catalog_id = Column(UUID(as_uuid=True), nullable=False)
    restoration_path = Column(Text)

    def __repr__(self) -> str:
        return f"<ArchivedImage(id={self.id}, archive_reason={self.archive_reason}, archived_at={self.archived_at})>"


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
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<DetectionThreshold(catalog_id={self.catalog_id}, layer={self.layer}, threshold={self.threshold})>"


class SuppressionPair(Base):
    """Permanent do-not-resurface index for reviewed pairs."""

    __tablename__ = "suppression_pairs"

    id_a = Column(Text, primary_key=True)
    id_b = Column(Text, primary_key=True)
    decision = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("id_a < id_b", name="ck_suppression_pair_ordered"),
    )

    def __repr__(self) -> str:
        return f"<SuppressionPair(id_a={self.id_a}, id_b={self.id_b}, decision={self.decision})>"
