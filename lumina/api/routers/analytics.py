"""Analytics and quality verification endpoints.

All routes are prefixed with /api/catalogs/{catalog_id}/analytics
by the router registration in app.py.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...db import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class CoverageItem(BaseModel):
    count: int
    pct: float


class HealthResponse(BaseModel):
    total: int
    coverage: Dict[str, CoverageItem]


class HistogramBucket(BaseModel):
    bucket: str
    count: int


class QualityResponse(BaseModel):
    total_scored: int
    total_unscored: int
    mean: Optional[float]
    median: Optional[float]
    histogram: List[HistogramBucket]
    verified_count: int
    verified_mean_delta: Optional[float]


class CameraEntry(BaseModel):
    make: Optional[str]
    model: Optional[str]
    count: int
    pct: float


class CamerasResponse(BaseModel):
    cameras: List[CameraEntry]
    unknown_count: int


class MonthEntry(BaseModel):
    year: int
    month: int
    count: int


class TimelineResponse(BaseModel):
    by_month: List[MonthEntry]


class FormatEntry(BaseModel):
    format: Optional[str]
    count: int
    pct: float


class FormatsResponse(BaseModel):
    formats: List[FormatEntry]


class SampleImage(BaseModel):
    id: str
    source_path: str
    thumbnail_url: str
    quality_score: Optional[int]
    quality_verified_score: Optional[int]
    format: Optional[str]
    width: Optional[int]
    height: Optional[int]
    camera_make: Optional[str]
    camera_model: Optional[str]
    format_score: Optional[float]
    resolution_score: Optional[float]
    size_score: Optional[float]
    metadata_score: Optional[float]


class SampleResponse(BaseModel):
    images: List[SampleImage]
    total_unverified: int


class VerifyRequest(BaseModel):
    image_id: str
    verified_score: int


class VerifyResponse(BaseModel):
    ok: bool


class ConfidenceTierItem(BaseModel):
    count: int
    pct: float


class OrganizationResponse(BaseModel):
    total: int
    organized: int
    not_organized: int
    organized_pct: float
    source_archived: int
    source_archived_pct: float
    by_confidence: Dict[str, ConfidenceTierItem]
    total_bytes: int
    organized_bytes: int
    not_organized_bytes: int


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _assert_catalog(catalog_id: str, db: Session) -> None:
    """Raise 404 if catalog does not exist."""
    row = db.execute(
        text("SELECT 1 FROM catalogs WHERE id = CAST(:cid AS uuid)"),
        {"cid": catalog_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Catalog not found")


def _pct(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(count / total * 100, 1)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/analytics/health", response_model=HealthResponse)
def analytics_health(catalog_id: str, db: Session = Depends(get_db)) -> HealthResponse:
    """Return enrichment coverage statistics for the catalog."""
    _assert_catalog(catalog_id, db)

    total_row = db.execute(
        text("SELECT COUNT(*) FROM images WHERE catalog_id = CAST(:cid AS uuid)"),
        {"cid": catalog_id},
    ).fetchone()
    total: int = total_row[0] if total_row else 0

    if total == 0:
        empty = CoverageItem(count=0, pct=0.0)
        return HealthResponse(
            total=0,
            coverage={
                "has_date": empty,
                "has_camera": empty,
                "has_format": empty,
                "has_clip": empty,
                "has_quality_score": empty,
                "has_tags": empty,
                "in_burst": empty,
                "quality_verified": empty,
            },
        )

    counts = db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE dates->>'selected_date' IS NOT NULL)            AS has_date,
                COUNT(*) FILTER (WHERE camera_make IS NOT NULL OR camera_model IS NOT NULL) AS has_camera,
                COUNT(*) FILTER (WHERE format IS NOT NULL)                              AS has_format,
                COUNT(*) FILTER (WHERE clip_embedding IS NOT NULL)                     AS has_clip,
                COUNT(*) FILTER (WHERE quality_score IS NOT NULL)                      AS has_quality_score,
                COUNT(*) FILTER (WHERE quality_verified_score IS NOT NULL)             AS quality_verified,
                COUNT(*) FILTER (WHERE burst_id IS NOT NULL)                           AS in_burst
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
            """
        ),
        {"cid": catalog_id},
    ).fetchone()

    # Tags: images that appear in image_tags at least once
    tags_row = db.execute(
        text(
            """
            SELECT COUNT(DISTINCT it.image_id)
            FROM image_tags it
            JOIN images i ON i.id = it.image_id
            WHERE i.catalog_id = CAST(:cid AS uuid)
            """
        ),
        {"cid": catalog_id},
    ).fetchone()
    has_tags_count: int = tags_row[0] if tags_row else 0

    assert counts is not None

    return HealthResponse(
        total=total,
        coverage={
            "has_date": CoverageItem(count=counts[0], pct=_pct(counts[0], total)),
            "has_camera": CoverageItem(count=counts[1], pct=_pct(counts[1], total)),
            "has_format": CoverageItem(count=counts[2], pct=_pct(counts[2], total)),
            "has_clip": CoverageItem(count=counts[3], pct=_pct(counts[3], total)),
            "has_quality_score": CoverageItem(
                count=counts[4], pct=_pct(counts[4], total)
            ),
            "has_tags": CoverageItem(
                count=has_tags_count, pct=_pct(has_tags_count, total)
            ),
            "in_burst": CoverageItem(count=counts[6], pct=_pct(counts[6], total)),
            "quality_verified": CoverageItem(
                count=counts[5], pct=_pct(counts[5], total)
            ),
        },
    )


# ---------------------------------------------------------------------------
# GET /quality
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/analytics/quality", response_model=QualityResponse)
def analytics_quality(
    catalog_id: str, db: Session = Depends(get_db)
) -> QualityResponse:
    """Return quality score distribution histogram and statistics."""
    _assert_catalog(catalog_id, db)

    stats_row = db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE quality_score IS NOT NULL)     AS total_scored,
                COUNT(*) FILTER (WHERE quality_score IS NULL)         AS total_unscored,
                AVG(quality_score::float)                             AS mean,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY quality_score) AS median,
                COUNT(*) FILTER (WHERE quality_verified_score IS NOT NULL) AS verified_count,
                AVG((quality_verified_score - quality_score)::float)
                    FILTER (WHERE quality_verified_score IS NOT NULL
                             AND quality_score IS NOT NULL)           AS verified_mean_delta
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
            """
        ),
        {"cid": catalog_id},
    ).fetchone()

    assert stats_row is not None
    total_scored, total_unscored, mean_val, median_val, verified_count, vmd = stats_row

    # Build histogram (10 buckets: 0-9, 10-19, ..., 90-100)
    bucket_rows = db.execute(
        text(
            """
            SELECT
                CASE
                    WHEN quality_score BETWEEN 0 AND 9   THEN 0
                    WHEN quality_score BETWEEN 10 AND 19  THEN 10
                    WHEN quality_score BETWEEN 20 AND 29  THEN 20
                    WHEN quality_score BETWEEN 30 AND 39  THEN 30
                    WHEN quality_score BETWEEN 40 AND 49  THEN 40
                    WHEN quality_score BETWEEN 50 AND 59  THEN 50
                    WHEN quality_score BETWEEN 60 AND 69  THEN 60
                    WHEN quality_score BETWEEN 70 AND 79  THEN 70
                    WHEN quality_score BETWEEN 80 AND 89  THEN 80
                    ELSE 90
                END AS bucket_start,
                COUNT(*) AS cnt
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
              AND quality_score IS NOT NULL
            GROUP BY bucket_start
            ORDER BY bucket_start
            """
        ),
        {"cid": catalog_id},
    ).fetchall()

    bucket_map: Dict[int, int] = {row[0]: row[1] for row in bucket_rows}
    bucket_labels = [
        (0, "0-9"),
        (10, "10-19"),
        (20, "20-29"),
        (30, "30-39"),
        (40, "40-49"),
        (50, "50-59"),
        (60, "60-69"),
        (70, "70-79"),
        (80, "80-89"),
        (90, "90-100"),
    ]
    histogram = [
        HistogramBucket(bucket=label, count=bucket_map.get(start, 0))
        for start, label in bucket_labels
    ]

    return QualityResponse(
        total_scored=total_scored,
        total_unscored=total_unscored,
        mean=round(mean_val, 2) if mean_val is not None else None,
        median=round(float(median_val), 2) if median_val is not None else None,
        histogram=histogram,
        verified_count=verified_count,
        verified_mean_delta=round(float(vmd), 2) if vmd is not None else None,
    )


# ---------------------------------------------------------------------------
# GET /cameras
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/analytics/cameras", response_model=CamerasResponse)
def analytics_cameras(
    catalog_id: str, db: Session = Depends(get_db)
) -> CamerasResponse:
    """Return camera make/model breakdown."""
    _assert_catalog(catalog_id, db)

    total_row = db.execute(
        text("SELECT COUNT(*) FROM images WHERE catalog_id = CAST(:cid AS uuid)"),
        {"cid": catalog_id},
    ).fetchone()
    total: int = total_row[0] if total_row else 0

    rows = db.execute(
        text(
            """
            SELECT camera_make, camera_model, COUNT(*) AS cnt
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
              AND (camera_make IS NOT NULL OR camera_model IS NOT NULL)
            GROUP BY camera_make, camera_model
            ORDER BY cnt DESC
            """
        ),
        {"cid": catalog_id},
    ).fetchall()

    cameras = [
        CameraEntry(
            make=row[0],
            model=row[1],
            count=row[2],
            pct=_pct(row[2], total),
        )
        for row in rows
    ]

    unknown_row = db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
              AND camera_make IS NULL
              AND camera_model IS NULL
            """
        ),
        {"cid": catalog_id},
    ).fetchone()
    unknown_count: int = unknown_row[0] if unknown_row else 0

    return CamerasResponse(cameras=cameras, unknown_count=unknown_count)


# ---------------------------------------------------------------------------
# GET /timeline
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/analytics/timeline", response_model=TimelineResponse)
def analytics_timeline(
    catalog_id: str, db: Session = Depends(get_db)
) -> TimelineResponse:
    """Return photo counts by year-month."""
    _assert_catalog(catalog_id, db)

    rows = db.execute(
        text(
            """
            SELECT
                EXTRACT(YEAR  FROM (dates->>'selected_date')::timestamptz)::int AS yr,
                EXTRACT(MONTH FROM (dates->>'selected_date')::timestamptz)::int AS mo,
                COUNT(*) AS cnt
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
              AND dates->>'selected_date' IS NOT NULL
              AND (dates->>'selected_date')::timestamptz BETWEEN '1900-01-01' AND now()
            GROUP BY yr, mo
            ORDER BY yr ASC, mo ASC
            """
        ),
        {"cid": catalog_id},
    ).fetchall()

    return TimelineResponse(
        by_month=[MonthEntry(year=row[0], month=row[1], count=row[2]) for row in rows]
    )


# ---------------------------------------------------------------------------
# GET /formats
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/analytics/formats", response_model=FormatsResponse)
def analytics_formats(
    catalog_id: str, db: Session = Depends(get_db)
) -> FormatsResponse:
    """Return format breakdown."""
    _assert_catalog(catalog_id, db)

    total_row = db.execute(
        text("SELECT COUNT(*) FROM images WHERE catalog_id = CAST(:cid AS uuid)"),
        {"cid": catalog_id},
    ).fetchone()
    total: int = total_row[0] if total_row else 0

    rows = db.execute(
        text(
            """
            SELECT format, COUNT(*) AS cnt
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
            GROUP BY format
            ORDER BY cnt DESC
            """
        ),
        {"cid": catalog_id},
    ).fetchall()

    formats = [
        FormatEntry(format=row[0], count=row[1], pct=_pct(row[1], total))
        for row in rows
    ]

    return FormatsResponse(formats=formats)


# ---------------------------------------------------------------------------
# Helpers for sample endpoint (defined outside loop to avoid B023)
# ---------------------------------------------------------------------------


def _make_safe_float(
    meta: Dict[str, Any],
) -> Any:
    def _inner(val: Any, key: str) -> Optional[float]:
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        v = meta.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        return None

    return _inner


def _make_safe_int(
    meta: Dict[str, Any],
) -> Any:
    def _inner(val: Any, key: str) -> Optional[int]:
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
        v = meta.get(key)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
        return None

    return _inner


def _make_safe_str(
    meta: Dict[str, Any],
) -> Any:
    def _inner(val: Any, key: str) -> Optional[str]:
        if val is not None:
            return str(val)
        v = meta.get(key)
        return str(v) if v is not None else None

    return _inner


# ---------------------------------------------------------------------------
# GET /quality/sample
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/analytics/quality/sample", response_model=SampleResponse)
def analytics_quality_sample(
    catalog_id: str,
    n: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SampleResponse:
    """Return N random scored images for hand verification.

    Preferentially returns images without a verified score.
    Recomputes component scores on the fly for display.
    """
    _assert_catalog(catalog_id, db)

    from ...analysis.quality_scorer import calculate_quality_score
    from ...core.types import FileType, ImageMetadata

    # Count total unverified scored images
    unverified_row = db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
              AND quality_score IS NOT NULL
              AND quality_verified_score IS NULL
            """
        ),
        {"cid": catalog_id},
    ).fetchone()
    total_unverified: int = unverified_row[0] if unverified_row else 0

    # Fetch random sample — prefer unverified, fallback to all scored
    rows = db.execute(
        text(
            """
            SELECT
                id,
                source_path,
                thumbnail_path,
                quality_score,
                quality_verified_score,
                format,
                width,
                height,
                size_bytes,
                file_type,
                camera_make,
                camera_model,
                lens_model,
                focal_length,
                aperture,
                shutter_speed,
                iso,
                latitude,
                longitude,
                metadata
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
              AND quality_score IS NOT NULL
              AND quality_verified_score IS NULL
            ORDER BY RANDOM()
            LIMIT :n
            """
        ),
        {"cid": catalog_id, "n": n},
    ).fetchall()

    # If we got fewer than n, top-up from verified images
    if len(rows) < n:
        remaining = n - len(rows)
        extra_rows = db.execute(
            text(
                """
                SELECT
                    id,
                    source_path,
                    thumbnail_path,
                    quality_score,
                    quality_verified_score,
                    format,
                    width,
                    height,
                    size_bytes,
                    file_type,
                    camera_make,
                    camera_model,
                    lens_model,
                    focal_length,
                    aperture,
                    shutter_speed,
                    iso,
                    latitude,
                    longitude,
                    metadata
                FROM images
                WHERE catalog_id = CAST(:cid AS uuid)
                  AND quality_score IS NOT NULL
                  AND quality_verified_score IS NOT NULL
                ORDER BY RANDOM()
                LIMIT :n
                """
            ),
            {"cid": catalog_id, "n": remaining},
        ).fetchall()
        rows = list(rows) + list(extra_rows)

    images: List[SampleImage] = []
    for row in rows:
        (
            img_id,
            source_path,
            thumbnail_path,
            quality_score,
            quality_verified_score,
            fmt,
            width,
            height,
            size_bytes,
            file_type_str,
            camera_make,
            camera_model,
            lens_model,
            focal_length,
            aperture,
            shutter_speed,
            iso,
            latitude,
            longitude,
            metadata_json,
        ) = row

        meta_dict: Dict[str, Any] = metadata_json or {}
        _safe_float = _make_safe_float(meta_dict)
        _safe_int = _make_safe_int(meta_dict)
        _safe_str = _make_safe_str(meta_dict)

        image_metadata = ImageMetadata(
            format=fmt,
            width=width,
            height=height,
            size_bytes=size_bytes,
            camera_make=camera_make,
            camera_model=camera_model,
            lens_model=lens_model,
            focal_length=_safe_float(focal_length, "focal_length"),
            aperture=_safe_float(aperture, "aperture"),
            shutter_speed=_safe_str(shutter_speed, "shutter_speed"),
            iso=_safe_int(iso, "iso"),
            gps_latitude=_safe_float(latitude, "gps_latitude"),
            gps_longitude=_safe_float(longitude, "gps_longitude"),
        )

        file_type = FileType.VIDEO if file_type_str == "video" else FileType.IMAGE

        try:
            score = calculate_quality_score(image_metadata, file_type)
            format_score: Optional[float] = score.format_score
            resolution_score: Optional[float] = score.resolution_score
            size_score: Optional[float] = score.size_score
            metadata_score: Optional[float] = score.metadata_score
        except Exception:
            format_score = resolution_score = size_score = metadata_score = None

        # Build thumbnail URL
        thumbnail_url = f"/api/catalogs/{catalog_id}/images/{img_id}/thumbnail"

        images.append(
            SampleImage(
                id=img_id,
                source_path=source_path,
                thumbnail_url=thumbnail_url,
                quality_score=quality_score,
                quality_verified_score=quality_verified_score,
                format=fmt,
                width=width,
                height=height,
                camera_make=camera_make,
                camera_model=camera_model,
                format_score=format_score,
                resolution_score=resolution_score,
                size_score=size_score,
                metadata_score=metadata_score,
            )
        )

    return SampleResponse(images=images, total_unverified=total_unverified)


# ---------------------------------------------------------------------------
# POST /quality/verify
# ---------------------------------------------------------------------------


@router.get("/{catalog_id}/analytics/organization", response_model=OrganizationResponse)
def analytics_organization(
    catalog_id: str, db: Session = Depends(get_db)
) -> OrganizationResponse:
    """Return organization and safety statistics for the catalog."""
    _assert_catalog(catalog_id, db)

    row = db.execute(
        text(
            """
            SELECT
                COUNT(*)                                                          AS total,
                COUNT(*) FILTER (WHERE organized_path IS NOT NULL)                AS organized,
                COUNT(*) FILTER (WHERE organized_path IS NULL)                    AS not_organized,
                COUNT(*) FILTER (
                    WHERE (processing_flags->>'source_archived')::boolean IS TRUE
                )                                                                 AS source_archived,
                COUNT(*) FILTER (
                    WHERE organized_path IS NOT NULL
                      AND processing_flags->>'organization_confidence' = 'resolved'
                )                                                                 AS conf_resolved,
                COUNT(*) FILTER (
                    WHERE organized_path IS NOT NULL
                      AND processing_flags->>'organization_confidence' = 'iffy'
                )                                                                 AS conf_iffy,
                COUNT(*) FILTER (
                    WHERE organized_path IS NOT NULL
                      AND processing_flags->>'organization_confidence' = 'date_only'
                )                                                                 AS conf_date_only,
                COUNT(*) FILTER (
                    WHERE organized_path IS NOT NULL
                      AND processing_flags->>'organization_confidence' = 'unresolved'
                )                                                                 AS conf_unresolved,
                COALESCE(SUM(size_bytes), 0)                                      AS total_bytes,
                COALESCE(SUM(size_bytes) FILTER (WHERE organized_path IS NOT NULL), 0)
                                                                                  AS organized_bytes,
                COALESCE(SUM(size_bytes) FILTER (WHERE organized_path IS NULL), 0)
                                                                                  AS not_organized_bytes
            FROM images
            WHERE catalog_id = CAST(:cid AS uuid)
              AND status_id NOT IN ('rejected', 'archived')
            """
        ),
        {"cid": catalog_id},
    ).fetchone()

    total = int(row.total or 0)
    organized = int(row.organized or 0)
    not_organized = int(row.not_organized or 0)
    source_archived = int(row.source_archived or 0)

    by_confidence: Dict[str, ConfidenceTierItem] = {}
    for tier in ("resolved", "iffy", "date_only", "unresolved"):
        count = int(getattr(row, f"conf_{tier}") or 0)
        by_confidence[tier] = ConfidenceTierItem(
            count=count, pct=_pct(count, organized)
        )

    return OrganizationResponse(
        total=total,
        organized=organized,
        not_organized=not_organized,
        organized_pct=_pct(organized, total),
        source_archived=source_archived,
        source_archived_pct=_pct(source_archived, organized) if organized else 0.0,
        by_confidence=by_confidence,
        total_bytes=int(row.total_bytes or 0),
        organized_bytes=int(row.organized_bytes or 0),
        not_organized_bytes=int(row.not_organized_bytes or 0),
    )


@router.post("/{catalog_id}/analytics/quality/verify", response_model=VerifyResponse)
def analytics_quality_verify(
    catalog_id: str,
    body: VerifyRequest,
    db: Session = Depends(get_db),
) -> VerifyResponse:
    """Save a human-verified quality rating for an image."""
    _assert_catalog(catalog_id, db)

    if not (0 <= body.verified_score <= 100):
        raise HTTPException(
            status_code=422, detail="verified_score must be between 0 and 100"
        )

    result = db.execute(
        text(
            """
            UPDATE images
            SET quality_verified_score = :vs,
                quality_verified_at    = NOW()
            WHERE id = :img_id
              AND catalog_id = CAST(:cid AS uuid)
            """
        ),
        {"vs": body.verified_score, "img_id": body.image_id, "cid": catalog_id},
    )
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Image not found in this catalog")

    return VerifyResponse(ok=True)
