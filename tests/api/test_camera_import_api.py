import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image as PILImage

from lumina.db.models import Catalog

pytestmark = pytest.mark.integration


@pytest.fixture
def catalog(db_session):
    catalog_id = uuid.uuid4()
    c = Catalog(
        id=catalog_id,
        name="Cam Test",
        schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
        source_directories=["/tmp"],
        organized_directory="/tmp/output",
    )
    db_session.add(c)
    db_session.commit()
    return c


def test_devices_returns_empty_when_no_mounts(client, catalog):
    with patch("pathlib.Path.exists", return_value=False):
        response = client.get(f"/api/catalogs/{catalog.id}/camera/devices")
    assert response.status_code == 200
    assert response.json() == []


def test_devices_returns_dcim_device(client, catalog, tmp_path):
    device_dir = tmp_path / "EOS_DIGITAL"
    dcim_dir = device_dir / "DCIM"
    dcim_dir.mkdir(parents=True)
    (dcim_dir / "IMG_001.JPG").write_bytes(b"fake")

    with patch(
        "lumina.api.routers.catalogs.DEVICE_MOUNT_ROOTS",
        [tmp_path],
    ):
        response = client.get(f"/api/catalogs/{catalog.id}/camera/devices")

    assert response.status_code == 200
    devices = response.json()
    assert len(devices) == 1
    assert devices[0]["name"] == "EOS_DIGITAL"
    assert devices[0]["file_count_estimate"] == 1


def test_discover_returns_new_files(client, catalog, tmp_path):
    img_path = tmp_path / "IMG_001.jpg"
    PILImage.new("RGB", (100, 100)).save(str(img_path))

    response = client.post(
        f"/api/catalogs/{catalog.id}/camera/discover",
        json={"device_path": str(tmp_path)},
    )
    assert response.status_code == 200
    files = response.json()
    assert len(files) == 1
    assert files[0]["filename"] == "IMG_001.jpg"
    assert files[0]["thumbnail_data_url"].startswith("data:image/jpeg;base64,")


def test_discover_skips_already_cataloged(client, catalog, db_session, tmp_path):
    from lumina.db.models import Image

    img_path = tmp_path / "IMG_002.jpg"
    PILImage.new("RGB", (100, 100)).save(str(img_path))

    existing = Image(
        id=str(uuid.uuid4()),
        catalog_id=str(catalog.id),
        source_path=str(img_path),
        file_type="image",
        checksum="abc123",
        size_bytes=100,
        dates={},
        metadata_json={},
    )
    db_session.add(existing)
    db_session.commit()

    response = client.post(
        f"/api/catalogs/{catalog.id}/camera/discover",
        json={"device_path": str(tmp_path)},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_discover_no_organized_directory_returns_400(client, db_session, tmp_path):
    catalog_id = uuid.uuid4()
    c = Catalog(
        id=catalog_id,
        name="No Output",
        schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
        source_directories=["/tmp"],
        organized_directory=None,
    )
    db_session.add(c)
    db_session.commit()

    response = client.post(
        f"/api/catalogs/{catalog_id}/camera/discover",
        json={"device_path": str(tmp_path)},
    )
    assert response.status_code == 400
