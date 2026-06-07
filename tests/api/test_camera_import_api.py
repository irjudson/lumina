import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image as PILImage

from lumina.db.models import Catalog


def _parse_ndjson(response):
    return [
        json.loads(line) for line in response.text.strip().split("\n") if line.strip()
    ]


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
    files = _parse_ndjson(response)
    assert len(files) == 1
    assert files[0]["filename"] == "IMG_001.jpg"
    assert files[0]["thumbnail_data_url"].startswith("data:image/jpeg;base64,")


def test_discover_skips_already_cataloged(client, catalog, tmp_path):
    from unittest.mock import MagicMock

    img_path = tmp_path / "IMG_002.jpg"
    PILImage.new("RGB", (100, 100)).save(str(img_path))

    # _check_already_imported uses get_db_context() (new connection, can't see test
    # savepoint data). Mock compute_checksum + get_db_context to simulate "already in DB".
    mock_db = MagicMock()
    mock_db.execute.return_value.first.return_value = (1,)
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_db)
    mock_cm.__exit__ = MagicMock(return_value=False)

    with (
        patch("lumina.analysis.scanner.compute_checksum", return_value="fixed_hash"),
        patch("lumina.db.get_db_context", return_value=mock_cm),
    ):
        response = client.post(
            f"/api/catalogs/{catalog.id}/camera/discover",
            json={"device_path": str(tmp_path)},
        )
    assert response.status_code == 200
    assert _parse_ndjson(response) == []


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


def test_discover_nonexistent_device_path_returns_404(client, catalog):
    response = client.post(
        f"/api/catalogs/{catalog.id}/camera/discover",
        json={"device_path": "/nonexistent/path/that/does/not/exist"},
    )
    assert response.status_code == 404
