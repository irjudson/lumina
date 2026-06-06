import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

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
