"""Tests for detect_events_job core algorithms.

Tests the haversine distance calculation, time-gap filtering, union-find clustering,
score calculation, and min_images/min_duration filtering without hitting a real database.
"""

from datetime import datetime, timedelta
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional, Tuple

# --- Inline helpers extracted from detect_events_job for unit testing ---


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Earth-radius haversine distance in km."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return R * 2 * atan2(sqrt(a), sqrt(1.0 - a))


def _parse_dt(s: str) -> datetime:
    """Parse a datetime string in any of the formats detect_events_job accepts."""
    s = s.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(
                s[
                    : len(
                        fmt.replace("%f", "ffffff")
                        .replace("%Y", "2000")
                        .replace("%m", "01")
                        .replace("%d", "01")
                        .replace("%H", "00")
                        .replace("%M", "00")
                        .replace("%S", "00")
                    )
                ],
                fmt,
            )
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s}")


def _cluster_images(
    images: List[Tuple[str, float, float, datetime]],
    max_radius_km: float,
    max_gap_h: float,
    min_images: int,
    min_duration_h: float,
) -> List[Dict[str, Any]]:
    """Run the union-find clustering algorithm from detect_events_job.

    Returns a list of event dicts (id, images, score, ...) after filtering.
    """
    if not images:
        return []

    parent = list(range(len(images)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(1, len(images)):
        _, lat_a, lon_a, dt_a = images[i - 1]
        _, lat_b, lon_b, dt_b = images[i]
        gap_h = (dt_b - dt_a).total_seconds() / 3600.0
        if gap_h < 0 or gap_h > max_gap_h:
            continue
        dist_km = _haversine(lat_a, lon_a, lat_b, lon_b)
        if dist_km <= max_radius_km:
            union(i - 1, i)

    from collections import defaultdict

    cluster_map: Dict[int, list] = defaultdict(list)
    for i, img in enumerate(images):
        cluster_map[find(i)].append(img)

    events = []
    for members in cluster_map.values():
        if len(members) < min_images:
            continue
        members.sort(key=lambda x: x[3])
        start_dt = members[0][3]
        end_dt = members[-1][3]
        duration_h = (end_dt - start_dt).total_seconds() / 3600.0
        if duration_h < min_duration_h:
            continue

        lats = [m[1] for m in members]
        lons = [m[2] for m in members]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)
        radius_km = max(_haversine(center_lat, center_lon, m[1], m[2]) for m in members)

        density = len(members) / max(duration_h, 0.25)
        spatial_bonus = 1.0 / (1.0 + radius_km)
        score = density * spatial_bonus

        events.append(
            {
                "image_ids": [m[0] for m in members],
                "image_count": len(members),
                "start_time": start_dt,
                "end_time": end_dt,
                "duration_h": duration_h,
                "center_lat": center_lat,
                "center_lon": center_lon,
                "radius_km": radius_km,
                "score": score,
            }
        )

    return events


# ============================= haversine tests =============================


class TestHaversine:
    """Test the haversine distance formula."""

    def test_same_point_is_zero(self):
        assert _haversine(0.0, 0.0, 0.0, 0.0) == 0.0

    def test_equator_one_degree_longitude(self):
        """One degree of longitude on the equator ≈ 111.3 km."""
        dist = _haversine(0.0, 0.0, 0.0, 1.0)
        assert 111.0 < dist < 111.7

    def test_known_cities(self):
        """NYC to LA is about 3940 km."""
        nyc = (40.7128, -74.0060)
        la = (34.0522, -118.2437)
        dist = _haversine(nyc[0], nyc[1], la[0], la[1])
        assert 3900 < dist < 4000

    def test_symmetry(self):
        """Distance A→B == B→A."""
        d1 = _haversine(37.0, -122.0, 38.0, -121.0)
        d2 = _haversine(38.0, -121.0, 37.0, -122.0)
        assert abs(d1 - d2) < 1e-9

    def test_quarter_mile_threshold(self):
        """Two points 0.25 miles (~0.402 km) apart should be within default radius."""
        # 0.402 km ≈ 0.00362 degrees latitude at equator
        lat1, lon1 = 37.7749, -122.4194  # San Francisco
        # Move ~0.4 km north (~0.0036 deg)
        lat2 = lat1 + 0.0036
        dist = _haversine(lat1, lon1, lat2, lon1)
        assert dist < 0.402 + 0.05  # within threshold with small margin


# ============================= parse_dt tests ==============================


class TestParseDt:
    """Test the datetime parser in detect_events_job."""

    def test_iso_with_microseconds(self):
        dt = _parse_dt("2023-06-15T14:30:00.123456")
        assert dt.year == 2023
        assert dt.month == 6
        assert dt.day == 15
        assert dt.hour == 14

    def test_iso_without_microseconds(self):
        dt = _parse_dt("2023-06-15T14:30:00")
        assert dt == datetime(2023, 6, 15, 14, 30, 0)

    def test_space_separated(self):
        dt = _parse_dt("2023-06-15 14:30:00")
        assert dt == datetime(2023, 6, 15, 14, 30, 0)

    def test_date_only(self):
        dt = _parse_dt("2023-06-15")
        assert dt.year == 2023
        assert dt.month == 6
        assert dt.day == 15

    def test_invalid_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Cannot parse date"):
            _parse_dt("not-a-date")


# ============================= clustering tests ============================

BASE_DT = datetime(2023, 6, 15, 10, 0, 0)
# San Francisco coordinates
SF_LAT, SF_LON = 37.7749, -122.4194


def _make_images(
    n: int,
    lat: float = SF_LAT,
    lon: float = SF_LON,
    interval_minutes: float = 5,
    start_dt: Optional[datetime] = None,
) -> List[Tuple[str, float, float, datetime]]:
    """Create n images at a fixed location with regular intervals."""
    base = start_dt or BASE_DT
    return [
        (f"img_{i}", lat, lon, base + timedelta(minutes=i * interval_minutes))
        for i in range(n)
    ]


class TestClustering:
    """Test the union-find clustering logic."""

    def test_single_cluster_all_nearby(self):
        """All images within radius and gap → single event."""
        images = _make_images(20, interval_minutes=5)
        events = _cluster_images(
            images,
            max_radius_km=0.402,
            max_gap_h=2.0,
            min_images=10,
            min_duration_h=1.0,
        )
        assert len(events) == 1
        assert events[0]["image_count"] == 20

    def test_min_images_filter(self):
        """Clusters smaller than min_images are dropped."""
        images = _make_images(5, interval_minutes=5)
        events = _cluster_images(
            images,
            max_radius_km=0.402,
            max_gap_h=2.0,
            min_images=10,
            min_duration_h=0.0,
        )
        assert events == []

    def test_min_duration_filter(self):
        """Clusters shorter than min_duration_h are dropped."""
        # 20 images, 1 minute apart → 19 minutes = 0.317 h < 0.5 h threshold
        images = _make_images(20, interval_minutes=1)
        events = _cluster_images(
            images,
            max_radius_km=0.402,
            max_gap_h=2.0,
            min_images=10,
            min_duration_h=0.5,
        )
        assert events == []

    def test_gap_splits_cluster(self):
        """Time gap > max_gap_h breaks cluster into two separate events."""
        # Group A: 12 images at 5-min intervals starting at 10:00
        group_a = _make_images(12, start_dt=BASE_DT, interval_minutes=5)
        # Group B: 12 images starting 3 hours after group A ends → gap > 2h
        a_end = group_a[-1][3]
        group_b_start = a_end + timedelta(hours=3)
        group_b = _make_images(12, start_dt=group_b_start, interval_minutes=5)
        all_images = group_a + group_b

        events = _cluster_images(
            all_images,
            max_radius_km=0.402,
            max_gap_h=2.0,
            min_images=10,
            min_duration_h=0.5,
        )
        assert len(events) == 2

    def test_distance_splits_cluster(self):
        """Images too far apart are NOT connected even if within time gap.

        SF images come first in time, LA images follow (gap < 2h so time
        alone wouldn't split them). The SF→LA transition has ~560 km distance
        which exceeds max_radius_km, so the union-find never bridges the groups.
        """
        # Group A at SF: 12 images, each 5 min apart
        group_a = _make_images(12, lat=37.7749, lon=-122.4194, interval_minutes=5)
        # Group B at LA: starts 1 hour after group A ends (gap = 1h < 2h)
        a_end = group_a[-1][3]
        la_start = a_end + timedelta(hours=1)
        group_b = _make_images(
            12, lat=34.0522, lon=-118.2437, interval_minutes=5, start_dt=la_start
        )
        # Combined, sorted by time — SF images are all before LA images
        all_images = group_a + group_b  # already sorted

        events = _cluster_images(
            all_images,
            max_radius_km=0.402,
            max_gap_h=2.0,
            min_images=10,
            min_duration_h=0.5,
        )
        # Each group is its own cluster (far apart)
        assert len(events) == 2

    def test_empty_images_returns_empty(self):
        events = _cluster_images([], 0.402, 2.0, 10, 1.0)
        assert events == []

    def test_all_same_time_fails_duration(self):
        """Images all at identical times have 0 duration → filtered by min_duration."""
        images = [(f"img_{i}", SF_LAT, SF_LON, BASE_DT) for i in range(20)]
        events = _cluster_images(images, 0.402, 2.0, min_images=5, min_duration_h=0.5)
        assert events == []

    def test_score_denser_event_ranks_higher(self):
        """An event with more images per hour should have a higher score."""
        # Dense event: 20 images over 1 hour
        dense = _make_images(20, interval_minutes=3)
        # Sparse event: 20 images over 5 hours
        sparse_start = BASE_DT + timedelta(days=1)
        sparse = _make_images(20, start_dt=sparse_start, interval_minutes=15)
        all_images = dense + sparse

        events = _cluster_images(
            all_images, 0.402, 2.0, min_images=10, min_duration_h=0.5
        )
        assert len(events) == 2
        # Sort by score desc
        events.sort(key=lambda e: e["score"], reverse=True)
        # Dense event (3-min intervals → ~57 min total) should outscore 5-hour sparse one
        assert events[0]["image_count"] == events[1]["image_count"] == 20
        dense_ev = next(
            e
            for e in events
            if (e["end_time"] - e["start_time"]).total_seconds() < 4000
        )
        sparse_ev = next(
            e
            for e in events
            if (e["end_time"] - e["start_time"]).total_seconds() > 4000
        )
        assert dense_ev["score"] > sparse_ev["score"]

    def test_score_tighter_radius_ranks_higher(self):
        """Smaller spatial radius → higher spatial_bonus → higher score."""
        # Tight cluster (same location)
        tight = _make_images(15, lat=SF_LAT, lon=SF_LON, interval_minutes=5)
        # Spread cluster (all images ~0.3 km apart in a line)
        spread = []
        spread_start = BASE_DT + timedelta(days=1)
        for i in range(15):
            lat = SF_LAT + i * 0.001  # ~0.11 km per step
            spread.append(
                (f"spread_{i}", lat, SF_LON, spread_start + timedelta(minutes=i * 5))
            )
        all_images = tight + spread

        events = _cluster_images(
            all_images, 2.0, 2.0, min_images=10, min_duration_h=0.5
        )
        assert len(events) == 2
        tight_ev = min(events, key=lambda e: e["radius_km"])
        spread_ev = max(events, key=lambda e: e["radius_km"])
        assert tight_ev["score"] > spread_ev["score"]

    def test_center_is_mean_of_coordinates(self):
        """Event center_lat/center_lon should be the arithmetic mean."""
        # Two images at known positions
        images = [
            ("a", 10.0, 20.0, BASE_DT),
            ("b", 10.0, 20.0, BASE_DT + timedelta(hours=2)),
            ("c", 12.0, 22.0, BASE_DT + timedelta(hours=4)),
        ]
        events = _cluster_images(
            images,
            max_radius_km=500.0,
            max_gap_h=10.0,
            min_images=3,
            min_duration_h=0.5,
        )
        assert len(events) == 1
        expected_lat = (10.0 + 10.0 + 12.0) / 3
        expected_lon = (20.0 + 20.0 + 22.0) / 3
        assert abs(events[0]["center_lat"] - expected_lat) < 1e-9
        assert abs(events[0]["center_lon"] - expected_lon) < 1e-9
