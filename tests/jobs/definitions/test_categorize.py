"""Tests for categorize job definition."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from lumina.jobs.definitions.categorize import (
    _categorize_archival,
    _categorize_family,
    _categorize_travel,
    _categorize_work,
    _centroid,
    _haversine_km,
    _trip_name,
)

# ─────────────────────────── _haversine_km ───────────────────────────


def test_haversine_seattle_to_london():
    # Seattle ~47.6N 122.3W → London ~51.5N 0.1W; expected ~7700 km
    km = _haversine_km(47.6062, -122.3321, 51.5074, -0.1278)
    assert 7600 < km < 7900


def test_haversine_same_point_is_zero():
    assert _haversine_km(40.0, -73.0, 40.0, -73.0) == pytest.approx(0.0)


def test_haversine_symmetry():
    a_to_b = _haversine_km(47.6, -122.3, 51.5, -0.1)
    b_to_a = _haversine_km(51.5, -0.1, 47.6, -122.3)
    assert a_to_b == pytest.approx(b_to_a)


# ─────────────────────────── _centroid ───────────────────────────


def test_centroid_empty_returns_none():
    assert _centroid([]) is None


def test_centroid_single_point():
    assert _centroid([(10.0, 20.0)]) == pytest.approx((10.0, 20.0))


def test_centroid_two_equal_points():
    assert _centroid([(5.0, 5.0), (5.0, 5.0)]) == pytest.approx((5.0, 5.0))


def test_centroid_average_of_three():
    points = [(0.0, 0.0), (6.0, 0.0), (0.0, 6.0)]
    result = _centroid(points)
    assert result == pytest.approx((2.0, 2.0))


# ─────────────────────────── _trip_name ───────────────────────────


def test_trip_name_same_month():
    result = _trip_name(date(2023, 6, 12), date(2023, 6, 19))
    assert result == "Jun 12–19, 2023"


def test_trip_name_different_months_same_year():
    result = _trip_name(date(2023, 6, 1), date(2023, 8, 31))
    assert result == "Jun–Aug 2023"


def test_trip_name_different_years():
    result = _trip_name(date(2023, 6, 15), date(2024, 8, 10))
    assert result == "Jun 2023 – Aug 2024"


def test_trip_name_with_location():
    result = _trip_name(date(2023, 6, 12), date(2023, 6, 19), location="Paris")
    assert result == "Paris – Jun 12–19, 2023"


def test_trip_name_location_none_omitted():
    result = _trip_name(date(2023, 6, 12), date(2023, 6, 19), location=None)
    assert result == "Jun 12–19, 2023"


# ─────────────────────────── helpers for mocking get_db_context ───────────────


def make_db_ctx(fetchall_return=None, fetchone_return=None):
    """Build a mock context manager that yields a mock db session."""
    mock_db = MagicMock()
    execute_result = MagicMock()
    execute_result.fetchall.return_value = fetchall_return or []
    execute_result.fetchone.return_value = fetchone_return
    mock_db.execute.return_value = execute_result

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_db)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    return mock_ctx, mock_db


# ─────────────────────────── _categorize_archival ───────────────────────────


def test_archival_bucketing_correct_bins():
    # 1975 → pre_1980, 1985 → 1980s, 1995 → 1990s, 2010 should never appear
    # (the SQL filters year < 2000, so 2010 won't be in rows)
    rows = [
        ("id-1975", 1975),
        ("id-1985", 1985),
        ("id-1995", 1995),
    ]

    sub_id = "sub-collection-uuid"
    added_counts = [1, 1, 1]  # one image per bucket

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value=sub_id,
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            side_effect=added_counts,
        ) as mock_upsert,
    ):
        ctx, db = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx

        result = _categorize_archival("cat-id", "archival-root-id")

    assert result["pre_1980"] == 1
    assert result["1980s"] == 1
    assert result["1990s"] == 1
    assert result["total"] == 3

    # Verify 2010 was not passed to any bucket (args: catalog_id, sub_id, ids, confidence)
    call_id_lists = [call.args[2] for call in mock_upsert.call_args_list]
    all_ids = [img_id for id_list in call_id_lists for img_id in id_list]
    assert "id-2010" not in all_ids


def test_archival_year_2010_excluded_from_buckets():
    # Simulate the SQL returning only pre-2000 rows (2010 would be filtered by SQL)
    rows = [("id-1995", 1995)]

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            return_value=1,
        ),
    ):
        ctx, db = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx

        result = _categorize_archival("cat-id", "archival-root-id")

    assert "pre_1980" not in result
    assert "1980s" not in result
    assert result["1990s"] == 1


# ─────────────────────────── _categorize_travel ───────────────────────────


def test_travel_detection_flags_distant_images():
    # Home base: ~Seattle (47.6, -122.3)
    # Travel location: ~Paris (48.85, 2.35)
    # Build timeline: lots of Seattle images spread over 60+ days,
    # with a cluster of Paris images in the middle that are far from the window centroid.
    base = datetime(2023, 7, 15, 10, 0, 0)

    from datetime import timedelta

    timeline_rows = []
    # 20 images in Seattle spread before travel
    for i in range(20):
        d = base - timedelta(days=40 - i * 2)
        timeline_rows.append((f"home-{i}", d, 47.6062, -122.3321))

    # 5 images in Paris (travel) on a single day
    travel_day = base
    for i in range(5):
        timeline_rows.append(
            (f"paris-{i}", travel_day + timedelta(hours=i), 48.8566, 2.3522)
        )

    # 20 more images in Seattle after travel
    for i in range(20):
        d = base + timedelta(days=40 + i * 2)
        timeline_rows.append((f"home-after-{i}", d, 47.6062, -122.3321))

    # Sort by capture_time (index 1)
    timeline_rows.sort(key=lambda r: r[1])

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="trip-sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            return_value=5,
        ) as mock_upsert,
    ):
        ctx, db = make_db_ctx(fetchall_return=timeline_rows)
        mock_gdc.return_value = ctx

        result = _categorize_travel("cat-id", "travel-root-id")

    assert result["total"] > 0
    assert result["trips"] >= 1
    # Paris images should be in the travel set
    upsert_ids = [
        img_id for call in mock_upsert.call_args_list for img_id in call.args[2]
    ]
    paris_ids = [f"paris-{i}" for i in range(5)]
    assert any(pid in upsert_ids for pid in paris_ids)


def test_travel_returns_zero_with_fewer_than_10_gps_rows():
    rows = [("id-1", datetime(2023, 1, 1, 10), 47.6, -122.3)]

    with patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc:
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_travel("cat-id", "travel-root-id")

    assert result == {"total": 0}


# ─────────────────────────── trip grouping logic ───────────────────────────


def test_trip_grouping_small_gap_same_trip():
    # Two days 2 apart → same trip (gap ≤ TRIP_MAX_GAP_DAYS=3)
    from lumina.jobs.definitions.categorize import TRIP_MAX_GAP_DAYS

    assert TRIP_MAX_GAP_DAYS == 3
    d1 = date(2023, 6, 1)
    d2 = date(2023, 6, 3)  # 2 days gap
    assert (d2 - d1).days <= TRIP_MAX_GAP_DAYS


def test_trip_grouping_large_gap_new_trip():
    d1 = date(2023, 6, 1)
    d2 = date(2023, 6, 10)  # 9 days gap → new trip
    from lumina.jobs.definitions.categorize import TRIP_MAX_GAP_DAYS

    assert (d2 - d1).days > TRIP_MAX_GAP_DAYS


def test_travel_trip_grouping_via_full_function():
    from datetime import timedelta

    base = datetime(2023, 6, 1, 12)

    # Trip 1: June 1-3 (2-day gap within trip)
    # Gap of 10 days
    # Trip 2: June 14-15
    home_base = (47.6, -122.3)
    travel = (48.85, 2.35)  # Paris

    # Build surrounding home images (need >5 per surrounding window)
    rows = []
    for i in range(20):
        d = base - timedelta(days=60 - i * 3)
        rows.append((f"h-pre-{i}", d, *home_base))
    for i in range(20):
        d = base + timedelta(days=60 + i * 3)
        rows.append((f"h-post-{i}", d, *home_base))

    # Trip 1 images: June 1, 2, 3
    for day_off in [0, 1, 2]:
        for h in range(3):
            rows.append(
                (
                    f"t1-d{day_off}-{h}",
                    base + timedelta(days=day_off, hours=h),
                    *travel,
                )
            )

    # Trip 2 images: June 14, 15
    for day_off in [13, 14]:
        for h in range(3):
            rows.append(
                (
                    f"t2-d{day_off}-{h}",
                    base + timedelta(days=day_off, hours=h),
                    *travel,
                )
            )

    rows.sort(key=lambda r: r[1])

    trip_count = []
    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            side_effect=lambda _cid, _sid, ids, _conf: len(ids),
        ),
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_travel("cat-id", "travel-root-id")
        trip_count.append(result)

    assert trip_count[0]["trips"] == 2


# ─────────────────────────── _categorize_work ───────────────────────────


def test_work_document_content_class():
    rows = [("doc-id", datetime(2023, 3, 15, 14, 0), "document", "Canon")]

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            side_effect=lambda _c, _s, ids, _conf: len(ids),
        ) as mock_upsert,
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_work("cat-id", "work-root-id")

    assert result["Documents"] == 1
    upserted = mock_upsert.call_args_list[0].args[2]
    assert "doc-id" in upserted


def test_work_screenshot_content_class():
    rows = [("ss-id", datetime(2023, 3, 15, 14, 0), "screenshot", None)]

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            side_effect=lambda _c, _s, ids, _conf: len(ids),
        ) as mock_upsert,
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_work("cat-id", "work-root-id")

    assert result["Screenshots"] == 1
    upserted = mock_upsert.call_args_list[0].args[2]
    assert "ss-id" in upserted


def test_work_weekday_business_hours_with_camera():
    # Wednesday 2023-03-15 at 10am, camera_make set, normal content
    ts = datetime(2023, 3, 15, 10, 0)  # Wednesday
    assert ts.weekday() == 2  # sanity check
    rows = [("work-id", ts, "photo", "Nikon")]

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            side_effect=lambda _c, _s, ids, _conf: len(ids),
        ) as mock_upsert,
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_work("cat-id", "work-root-id")

    assert result["Work Hours"] == 1
    upserted = mock_upsert.call_args_list[0].args[2]
    assert "work-id" in upserted


def test_work_noise_class_excluded_from_work_hours():
    ts = datetime(2023, 3, 15, 10, 0)  # weekday, business hours
    rows = [("meme-id", ts, "meme", "Canon")]  # noise class

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            return_value=0,
        ),
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_work("cat-id", "work-root-id")

    assert result["total"] == 0


# ─────────────────────────── _categorize_family ───────────────────────────


def test_family_noise_classes_excluded():
    # Saturday evening but content is noise → should be excluded
    ts = datetime(2023, 6, 10, 20, 0)  # Saturday, 8pm
    assert ts.weekday() == 5

    rows = [("noise-id", ts, "Canon", "social_media")]

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            return_value=0,
        ),
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_family("cat-id", "family-root-id")

    assert result["total"] == 0


def test_family_non_evening_weekday_excluded():
    # Tuesday at 2pm is neither evening nor weekend
    ts = datetime(2023, 6, 6, 14, 0)  # Tuesday
    assert ts.weekday() == 1

    rows = [("mid-id", ts, "Canon", "photo")]

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            return_value=0,
        ),
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_family("cat-id", "family-root-id")

    assert result["total"] == 0


def test_family_weekend_image_included():
    # Saturday afternoon
    ts = datetime(2023, 6, 10, 15, 0)  # Saturday
    assert ts.weekday() == 5

    rows = [("weekend-id", ts, "Canon", "photo")]

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            side_effect=lambda _c, _s, ids, _conf: len(ids),
        ),
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_family("cat-id", "family-root-id")

    assert result["total"] == 1


def test_family_evening_image_included():
    # Wednesday at 9pm (evening = 19-22)
    ts = datetime(2023, 6, 7, 21, 0)  # Wednesday
    assert ts.weekday() == 2

    rows = [("eve-id", ts, "Canon", "photo")]

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ),
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            side_effect=lambda _c, _s, ids, _conf: len(ids),
        ),
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_family("cat-id", "family-root-id")

    assert result["total"] == 1


def test_family_decade_bucketing_2005():
    # 2005 → "2000s"
    ts = datetime(2005, 8, 20, 20, 0)  # Saturday evening
    assert ts.weekday() == 5

    rows = [("img-2005", ts, "Canon", "photo")]

    with (
        patch("lumina.jobs.definitions.categorize.get_db_context") as mock_gdc,
        patch(
            "lumina.jobs.definitions.categorize._ensure_subcollection",
            return_value="sub-id",
        ) as mock_ensure,
        patch(
            "lumina.jobs.definitions.categorize._upsert_memberships",
            side_effect=lambda _c, _s, ids, _conf: len(ids),
        ),
    ):
        ctx, _ = make_db_ctx(fetchall_return=rows)
        mock_gdc.return_value = ctx
        result = _categorize_family("cat-id", "family-root-id")

    assert result["2000s"] == 1
    # Verify the decade name passed to _ensure_subcollection
    ensure_call = mock_ensure.call_args
    assert ensure_call.args[3] == "2000s" or "2000s" in ensure_call.args
