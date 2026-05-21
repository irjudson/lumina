"""Tests for the collections API endpoints.

Tests:
    GET  /api/catalogs/{catalog_id}/collections/
    POST /api/catalogs/{catalog_id}/collections/
    GET  /api/catalogs/{catalog_id}/collections/{id}/
    DELETE /api/catalogs/{catalog_id}/collections/{id}/
    POST /api/catalogs/{catalog_id}/collections/{id}/confirm
    POST /api/catalogs/{catalog_id}/collections/{id}/reject
"""

import uuid

import pytest
from sqlalchemy import text

from lumina.db.models import Catalog

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def coll_catalog(db_session) -> uuid.UUID:
    catalog_id = uuid.uuid4()
    catalog = Catalog(
        id=catalog_id,
        name="Collections Test Catalog",
        schema_name=f"test_coll_{catalog_id.hex[:8]}",
        source_directories=["/test/collections"],
    )
    db_session.add(catalog)
    db_session.commit()
    db_session.refresh(catalog)
    return catalog_id


@pytest.fixture
def test_image_id(db_session, coll_catalog) -> str:
    img_id = f"coll_img_{uuid.uuid4().hex[:8]}"
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
            "cid": str(coll_catalog),
            "path": "/test/collections/img.jpg",
            "chk": f"chk_coll_{img_id}",
        },
    )
    db_session.commit()
    return img_id


def _insert_collection(
    db_session,
    catalog_id: uuid.UUID,
    name: str,
    source: str = "user",
    parent_id=None,
    system_key=None,
) -> str:
    coll_id = str(uuid.uuid4())
    db_session.execute(
        text(
            """
            INSERT INTO collections (id, catalog_id, name, source, system_key,
                parent_id, created_at, updated_at)
            VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :name, :source,
                :skey,
                CAST(:pid AS uuid),
                NOW(), NOW())
            """
        ),
        {
            "id": coll_id,
            "cid": str(catalog_id),
            "name": name,
            "source": source,
            "skey": system_key,
            "pid": parent_id,
        },
    )
    db_session.commit()
    return coll_id


def _insert_collection_image(
    db_session, collection_id: str, image_id: str, confirmed: bool = True
):
    db_session.execute(
        text(
            """
            INSERT INTO collection_images
                (id, collection_id, image_id, position, confirmed, confidence,
                 source, added_at)
            VALUES (CAST(:id AS uuid), CAST(:cid AS uuid), :iid, 0,
                :confirmed, 0.9, 'system', NOW())
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "cid": collection_id,
            "iid": image_id,
            "confirmed": confirmed,
        },
    )
    db_session.commit()


# ---------------------------------------------------------------------------
# GET /api/catalogs/{catalog_id}/collections/
# ---------------------------------------------------------------------------


class TestListCollections:
    def test_empty_catalog_returns_empty_list(self, client, coll_catalog):
        resp = client.get(f"/api/catalogs/{coll_catalog}/collections")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_top_level_collections_only(self, client, db_session, coll_catalog):
        parent_id = _insert_collection(db_session, coll_catalog, "Parent")
        _insert_collection(db_session, coll_catalog, "Child", parent_id=parent_id)
        resp = client.get(f"/api/catalogs/{coll_catalog}/collections")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()]
        assert "Parent" in names
        assert "Child" not in names

    def test_filter_by_parent_id_returns_children(
        self, client, db_session, coll_catalog
    ):
        parent_id = _insert_collection(db_session, coll_catalog, "AlbumParent")
        _insert_collection(db_session, coll_catalog, "Sub1", parent_id=parent_id)
        _insert_collection(db_session, coll_catalog, "Sub2", parent_id=parent_id)
        resp = client.get(
            f"/api/catalogs/{coll_catalog}/collections",
            params={"parent_id": parent_id},
        )
        assert resp.status_code == 200
        names = {c["name"] for c in resp.json()}
        assert names == {"Sub1", "Sub2"}

    def test_child_count_field_present(self, client, db_session, coll_catalog):
        parent_id = _insert_collection(db_session, coll_catalog, "WithKids")
        _insert_collection(db_session, coll_catalog, "Kid", parent_id=parent_id)
        resp = client.get(f"/api/catalogs/{coll_catalog}/collections")
        assert resp.status_code == 200
        item = next(c for c in resp.json() if c["name"] == "WithKids")
        assert item["child_count"] == 1


# ---------------------------------------------------------------------------
# POST /api/catalogs/{catalog_id}/collections/
# ---------------------------------------------------------------------------


class TestCreateCollection:
    def test_create_valid_collection(self, client, coll_catalog):
        resp = client.post(
            f"/api/catalogs/{coll_catalog}/collections",
            json={"name": "Vacation 2025"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Vacation 2025"
        assert "id" in data
        assert data["source"] == "user"
        assert data["image_ids"] == []

    def test_create_sub_collection(self, client, db_session, coll_catalog):
        parent_id = _insert_collection(db_session, coll_catalog, "Trips")
        resp = client.post(
            f"/api/catalogs/{coll_catalog}/collections",
            json={"name": "Paris Trip", "parent_id": parent_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["parent_id"] == parent_id
        assert data["source"] == "user"

    def test_three_level_hierarchy_rejected(self, client, db_session, coll_catalog):
        grandparent_id = _insert_collection(db_session, coll_catalog, "Grandparent")
        parent_id = _insert_collection(
            db_session, coll_catalog, "Parent", parent_id=grandparent_id
        )
        resp = client.post(
            f"/api/catalogs/{coll_catalog}/collections",
            json={"name": "Child", "parent_id": parent_id},
        )
        assert resp.status_code == 400
        assert "2 levels" in resp.json()["detail"]

    def test_source_is_always_user(self, client, coll_catalog):
        resp = client.post(
            f"/api/catalogs/{coll_catalog}/collections",
            json={"name": "SystemAttempt"},
        )
        assert resp.status_code == 200
        assert resp.json()["source"] == "user"

    def test_unknown_catalog_returns_404(self, client):
        resp = client.post(
            f"/api/catalogs/{uuid.uuid4()}/collections",
            json={"name": "Ghost"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/catalogs/{catalog_id}/collections/{id}/
# ---------------------------------------------------------------------------


class TestGetCollection:
    def test_get_collection_no_members(self, client, db_session, coll_catalog):
        coll_id = _insert_collection(db_session, coll_catalog, "Empty")
        resp = client.get(f"/api/catalogs/{coll_catalog}/collections/{coll_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == coll_id
        assert data["image_ids"] == []

    def test_get_collection_only_confirmed_images(
        self, client, db_session, coll_catalog, test_image_id
    ):
        coll_id = _insert_collection(db_session, coll_catalog, "Mixed")
        # confirmed member
        _insert_collection_image(db_session, coll_id, test_image_id, confirmed=True)
        # unconfirmed second image (insert as a second image directly)
        img2_id = f"coll_img_{uuid.uuid4().hex[:8]}"
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
                "id": img2_id,
                "cid": str(coll_catalog),
                "path": "/test/collections/img2.jpg",
                "chk": f"chk2_{img2_id}",
            },
        )
        db_session.commit()
        _insert_collection_image(db_session, coll_id, img2_id, confirmed=False)

        resp = client.get(f"/api/catalogs/{coll_catalog}/collections/{coll_id}")
        assert resp.status_code == 200
        assert resp.json()["image_ids"] == [test_image_id]

    def test_get_unknown_collection_returns_404(self, client, coll_catalog):
        resp = client.get(f"/api/catalogs/{coll_catalog}/collections/{uuid.uuid4()}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/catalogs/{catalog_id}/collections/{id}/
# ---------------------------------------------------------------------------


class TestDeleteCollection:
    def test_delete_user_collection(self, client, db_session, coll_catalog):
        coll_id = _insert_collection(
            db_session, coll_catalog, "ToDelete", source="user"
        )
        resp = client.delete(f"/api/catalogs/{coll_catalog}/collections/{coll_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        resp2 = client.get(f"/api/catalogs/{coll_catalog}/collections/{coll_id}")
        assert resp2.status_code == 404

    def test_delete_top_level_system_collection_returns_409(
        self, client, db_session, coll_catalog
    ):
        coll_id = _insert_collection(
            db_session,
            coll_catalog,
            "SysCategory",
            source="system",
            system_key="people",
        )
        resp = client.delete(f"/api/catalogs/{coll_catalog}/collections/{coll_id}")
        assert resp.status_code == 409

    def test_delete_system_sub_collection_allowed(
        self, client, db_session, coll_catalog
    ):
        parent_id = _insert_collection(
            db_session, coll_catalog, "SysParent", source="system", system_key="events"
        )
        child_id = _insert_collection(
            db_session, coll_catalog, "SysChild", source="system", parent_id=parent_id
        )
        resp = client.delete(f"/api/catalogs/{coll_catalog}/collections/{child_id}")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /confirm and /reject
# ---------------------------------------------------------------------------


class TestConfirmMemberships:
    def test_confirm_unconfirmed_members(
        self, client, db_session, coll_catalog, test_image_id
    ):
        coll_id = _insert_collection(db_session, coll_catalog, "ToConfirm")
        _insert_collection_image(db_session, coll_id, test_image_id, confirmed=False)

        resp = client.post(
            f"/api/catalogs/{coll_catalog}/collections/{coll_id}/confirm",
            json={"image_ids": [test_image_id]},
        )
        assert resp.status_code == 200
        assert resp.json()["confirmed"] == 1

        detail = client.get(
            f"/api/catalogs/{coll_catalog}/collections/{coll_id}"
        ).json()
        assert test_image_id in detail["image_ids"]

    def test_confirm_already_confirmed_is_noop(
        self, client, db_session, coll_catalog, test_image_id
    ):
        coll_id = _insert_collection(db_session, coll_catalog, "AlreadyConfirmed")
        _insert_collection_image(db_session, coll_id, test_image_id, confirmed=True)

        resp = client.post(
            f"/api/catalogs/{coll_catalog}/collections/{coll_id}/confirm",
            json={"image_ids": [test_image_id]},
        )
        assert resp.status_code == 200
        assert resp.json()["confirmed"] == 0


class TestRejectMemberships:
    def test_reject_removes_unconfirmed_members(
        self, client, db_session, coll_catalog, test_image_id
    ):
        coll_id = _insert_collection(db_session, coll_catalog, "ToReject")
        _insert_collection_image(db_session, coll_id, test_image_id, confirmed=False)

        resp = client.post(
            f"/api/catalogs/{coll_catalog}/collections/{coll_id}/reject",
            json={"image_ids": [test_image_id]},
        )
        assert resp.status_code == 200
        assert resp.json()["rejected"] == 1

        detail = client.get(
            f"/api/catalogs/{coll_catalog}/collections/{coll_id}"
        ).json()
        assert test_image_id not in detail["image_ids"]

    def test_reject_confirmed_member_is_noop(
        self, client, db_session, coll_catalog, test_image_id
    ):
        coll_id = _insert_collection(db_session, coll_catalog, "RejectConfirmed")
        _insert_collection_image(db_session, coll_id, test_image_id, confirmed=True)

        resp = client.post(
            f"/api/catalogs/{coll_catalog}/collections/{coll_id}/reject",
            json={"image_ids": [test_image_id]},
        )
        assert resp.status_code == 200
        assert resp.json()["rejected"] == 0

        detail = client.get(
            f"/api/catalogs/{coll_catalog}/collections/{coll_id}"
        ).json()
        assert test_image_id in detail["image_ids"]
