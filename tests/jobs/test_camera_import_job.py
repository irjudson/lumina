import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from PIL import Image as PILImage

from lumina.db.models import Catalog, Image
from lumina.jobs.definitions.camera_import import camera_import_job
from lumina.jobs.types import JobContext

pytestmark = pytest.mark.integration


@pytest.fixture
def catalog_with_output(db_session, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    catalog_id = uuid.uuid4()
    catalog = Catalog(
        id=catalog_id,
        name="Test",
        schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
        source_directories=[str(tmp_path / "src")],
        organized_directory=str(output_dir),
    )
    db_session.add(catalog)
    db_session.commit()
    return catalog, output_dir


@pytest.fixture
def source_image(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    img_path = src / "IMG_001.jpg"
    PILImage.new("RGB", (100, 100), color=(128, 0, 0)).save(str(img_path))
    return img_path


def test_camera_import_copies_and_catalogs(
    catalog_with_output, source_image, db_session
):
    catalog, output_dir = catalog_with_output

    ctx = JobContext(
        job_id=str(uuid.uuid4()),
        catalog_id=str(catalog.id),
        parameters={
            "file_paths": [str(source_image)],
            "delete_source": False,
        },
    )

    result = camera_import_job(ctx)

    assert result["copied"] == 1
    assert result["cataloged"] == 1
    assert result["failed"] == 0
    assert source_image.exists()
    copied = list(output_dir.rglob("*.jpg"))
    assert len(copied) == 1


def test_camera_import_delete_source(catalog_with_output, source_image, db_session):
    catalog, output_dir = catalog_with_output

    ctx = JobContext(
        job_id=str(uuid.uuid4()),
        catalog_id=str(catalog.id),
        parameters={
            "file_paths": [str(source_image)],
            "delete_source": True,
        },
    )

    camera_import_job(ctx)

    assert not source_image.exists()
    copied_files = list(output_dir.rglob("*.jpg"))
    assert len(copied_files) == 1


def test_camera_import_missing_file(catalog_with_output, db_session):
    catalog, output_dir = catalog_with_output

    ctx = JobContext(
        job_id=str(uuid.uuid4()),
        catalog_id=str(catalog.id),
        parameters={
            "file_paths": ["/nonexistent/IMG_999.jpg"],
            "delete_source": False,
        },
    )

    result = camera_import_job(ctx)

    assert result["failed"] == 1
    assert result["copied"] == 0
    assert result["cataloged"] == 0


def test_camera_import_no_organized_directory(db_session, tmp_path):
    catalog_id = uuid.uuid4()
    catalog = Catalog(
        id=catalog_id,
        name="No Output",
        schema_name=f"catalog_{str(catalog_id).replace('-', '_')}",
        source_directories=[str(tmp_path)],
        organized_directory=None,
    )
    db_session.add(catalog)
    db_session.commit()

    ctx = JobContext(
        job_id=str(uuid.uuid4()),
        catalog_id=str(catalog_id),
        parameters={"file_paths": [str(tmp_path / "x.jpg")], "delete_source": False},
    )

    result = camera_import_job(ctx)
    assert result["error"] == "no_organized_directory"
