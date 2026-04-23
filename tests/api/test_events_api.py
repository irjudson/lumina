"""Tests for the events API endpoints.

Tests GET /api/catalogs/{catalog_id}/events
     GET /api/catalogs/{catalog_id}/events/{event_id}/images
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from lumina.db.models import Catalog, Image

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def ensure_events_tables(engine, tables_created):
    """Apply the events schema migration so event tables exist in the test DB."""
    from lumina.db.migrations.events_schema import upgrade

    upgrade(engine)


@pytest.fixture
def events_catalog(db_session) -> uuid.UUID:
    """Create a catalog for events tests."""
    catalog_id = uuid.uuid4()
    catalog = Catalog(
        id=catalog_id,
        name="Events Test Catalog",
        schema_name=f"test_events_{catalog_id.hex[:8]}",
        source_directories=["/test/events"],
    )
    db_session.add(catalog)
    db_session.commit()
    db_session.refresh(catalog)
    return catalog_id


@pytest.fixture
def seeded_event(db_session, events_catalog):
    """Insert one event with two linked images into the test database.

    Returns (catalog_id, event_id, [image_id_1, image_id_2]).
    """
    catalog_id = events_catalog

    # Insert images
    now = datetime.utcnow()
    img_ids = []
    for i in range(2):
        img_id = f"evt_img_{uuid.uuid4().hex[:8]}"
        db_session.execute(
            text(
                """
                INSERT INTO images (id, catalog_id, source_path, file_type,
                    checksum, dates, metadata, created_at, updated_at)
                VALUES (:id, CAST(:cid AS uuid), :path, 'image',
                    :chk, '{}', '{}', NOW(), NOW())
            """
            ),
            {
                "id": img_id,
                "cid": str(catalog_id),
                "path": f"/test/events/img{i}.jpg",
                "chk": f"chk_event_{i}",
            },
        )
        img_ids.append(img_id)

    # Insert event
    event_id = str(uuid.uuid4())
    start = now - timedelta(hours=2)
    end = now
    db_session.execute(
        text(
            """
            INSERT INTO events (id, catalog_id, start_time, end_time,
                duration_minutes, image_count, center_lat, center_lon,
                radius_km, score, detected_at)
            VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :start, :end,
                :dur, :cnt, :lat, :lon, :rad, :score, NOW())
        """
        ),
        {
            "id": event_id,
            "cid": str(catalog_id),
            "start": start,
            "end": end,
            "dur": 120,
            "cnt": 2,
            "lat": 37.7749,
            "lon": -122.4194,
            "rad": 0.1,
            "score": 15.5,
        },
    )

    # Link images to event
    for img_id in img_ids:
        db_session.execute(
            text(
                """
                INSERT INTO event_images (event_id, image_id)
                VALUES (CAST(:eid AS uuid), :img_id)
                ON CONFLICT DO NOTHING
            """
            ),
            {"eid": event_id, "img_id": img_id},
        )

    db_session.commit()
    return catalog_id, event_id, img_ids


class TestListEventsEndpoint:
    """GET /api/catalogs/{catalog_id}/events"""

    def test_empty_catalog_returns_zero(self, client, events_catalog):
        """Catalog with no events returns empty list and total=0."""
        resp = client.get(f"/api/catalogs/{events_catalog}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["events"] == []

    def test_returns_seeded_event(self, client, seeded_event):
        """Returns the single seeded event with correct fields."""
        catalog_id, event_id, _ = seeded_event
        resp = client.get(f"/api/catalogs/{catalog_id}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        ev = data["events"][0]
        assert ev["id"] == event_id
        assert ev["image_count"] == 2
        assert ev["score"] == 15.5
        assert ev["center_lat"] == pytest.approx(37.7749)
        assert ev["center_lon"] == pytest.approx(-122.4194)

    def test_required_fields_present(self, client, seeded_event):
        """Every event dict has the expected keys."""
        catalog_id, _, _ = seeded_event
        resp = client.get(f"/api/catalogs/{catalog_id}/events")
        assert resp.status_code == 200
        ev = resp.json()["events"][0]
        for key in (
            "id",
            "name",
            "start_time",
            "end_time",
            "duration_minutes",
            "image_count",
            "center_lat",
            "center_lon",
            "radius_km",
            "score",
            "detected_at",
        ):
            assert key in ev, f"Missing key: {key}"

    def test_multiple_events_sorted_by_score(self, client, db_session, events_catalog):
        """Events are returned sorted by score descending."""
        catalog_id = events_catalog
        base = datetime(2023, 1, 1, 10, 0, 0)

        for score in (5.0, 25.0, 10.0):
            eid = str(uuid.uuid4())
            db_session.execute(
                text(
                    """
                    INSERT INTO events (id, catalog_id, start_time, end_time,
                        duration_minutes, image_count, center_lat, center_lon,
                        radius_km, score, detected_at)
                    VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :start, :end,
                        60, 10, 0, 0, 0.1, :score, NOW())
                """
                ),
                {
                    "id": eid,
                    "cid": str(catalog_id),
                    "start": base,
                    "end": base + timedelta(hours=1),
                    "score": score,
                },
            )
        db_session.commit()

        resp = client.get(f"/api/catalogs/{catalog_id}/events", params={"limit": 10})
        assert resp.status_code == 200
        events = resp.json()["events"]
        scores = [e["score"] for e in events]
        assert scores == sorted(scores, reverse=True)

    def test_pagination_limit_offset(self, client, db_session, events_catalog):
        """Limit and offset parameters paginate results correctly."""
        catalog_id = events_catalog
        base = datetime(2023, 6, 1, 9, 0, 0)

        # Insert 5 events with distinct scores
        for i in range(5):
            eid = str(uuid.uuid4())
            db_session.execute(
                text(
                    """
                    INSERT INTO events (id, catalog_id, start_time, end_time,
                        duration_minutes, image_count, center_lat, center_lon,
                        radius_km, score, detected_at)
                    VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :start, :end,
                        60, 10, 0, 0, 0.1, :score, NOW())
                """
                ),
                {
                    "id": eid,
                    "cid": str(catalog_id),
                    "start": base,
                    "end": base + timedelta(hours=1),
                    "score": float(i + 1),
                },
            )
        db_session.commit()

        # First page
        r1 = client.get(
            f"/api/catalogs/{catalog_id}/events", params={"limit": 2, "offset": 0}
        )
        assert r1.status_code == 200
        page1 = r1.json()
        assert len(page1["events"]) == 2

        # Second page
        r2 = client.get(
            f"/api/catalogs/{catalog_id}/events", params={"limit": 2, "offset": 2}
        )
        assert r2.status_code == 200
        page2 = r2.json()
        assert len(page2["events"]) == 2

        # No overlap between pages
        ids1 = {e["id"] for e in page1["events"]}
        ids2 = {e["id"] for e in page2["events"]}
        assert ids1.isdisjoint(ids2)


class TestListEventImagesEndpoint:
    """GET /api/catalogs/{catalog_id}/events/{event_id}/images"""

    def test_returns_linked_images(self, client, seeded_event):
        """Returns images linked to the event."""
        catalog_id, event_id, img_ids = seeded_event
        resp = client.get(f"/api/catalogs/{catalog_id}/events/{event_id}/images")
        assert resp.status_code == 200
        data = resp.json()
        returned_ids = {img["id"] for img in data["images"]}
        assert returned_ids == set(img_ids)

    def test_total_matches_image_count(self, client, seeded_event):
        """total field equals len(images)."""
        catalog_id, event_id, _ = seeded_event
        resp = client.get(f"/api/catalogs/{catalog_id}/events/{event_id}/images")
        data = resp.json()
        assert data["total"] == len(data["images"])

    def test_image_fields_present(self, client, seeded_event):
        """Each image has id, source_path, file_type fields."""
        catalog_id, event_id, _ = seeded_event
        resp = client.get(f"/api/catalogs/{catalog_id}/events/{event_id}/images")
        assert resp.status_code == 200
        for img in resp.json()["images"]:
            assert "id" in img
            assert "source_path" in img
            assert "file_type" in img

    def test_unknown_event_returns_empty(self, client, events_catalog):
        """Event that doesn't exist returns empty images list."""
        fake_event = str(uuid.uuid4())
        resp = client.get(f"/api/catalogs/{events_catalog}/events/{fake_event}/images")
        assert resp.status_code == 200
        data = resp.json()
        assert data["images"] == []
        assert data["total"] == 0
