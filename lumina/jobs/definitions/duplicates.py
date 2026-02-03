"""Duplicate detection job definition.

Computes perceptual hashes and groups similar images.
"""

from typing import Any, Callable, Dict, List, Optional

from ..framework import ParallelJob, register_job


def discover_images_for_hashing(
    catalog_id: str,
    images_provider: Optional[Callable[[str], List[str]]] = None,
) -> List[str]:
    """Find images that need hash computation.

    Args:
        catalog_id: The catalog UUID
        images_provider: Optional function to get image IDs
                        (defaults to database lookup)

    Returns:
        List of image IDs without hashes
    """
    if images_provider:
        return images_provider(catalog_id)

    # Default: use database lookup
    from lumina.db.models import Image
    from lumina.db.session import get_db_session

    with get_db_session() as session:
        images = (
            session.query(Image)
            .filter(Image.catalog_id == catalog_id)
            .filter(Image.dhash.is_(None))
            .all()
        )
        return [str(img.id) for img in images]


def compute_image_hashes(
    image_id: str,
    catalog_id: str,
    path_provider: Optional[Callable[[str, str], str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Compute perceptual hashes for an image.

    Args:
        image_id: The image ID
        catalog_id: The catalog UUID
        path_provider: Optional function to get image path
                      (defaults to database lookup)
        **kwargs: Additional processing options

    Returns:
        Hash computation result
    """
    from lumina.analysis.hashing import compute_all_hashes

    # Get image path
    if path_provider:
        path = path_provider(catalog_id, image_id)
    else:
        # Default: use database lookup
        from lumina.db.models import Image
        from lumina.db.session import get_db_session

        with get_db_session() as session:
            image = session.query(Image).filter(Image.id == image_id).first()
            path = image.file_path if image else ""

    try:
        hashes = compute_all_hashes(path)
        return {
            "image_id": image_id,
            "hashes": hashes,
            "success": True,
        }
    except Exception as e:
        return {
            "image_id": image_id,
            "error": str(e),
            "success": False,
        }


def finalize_duplicates(
    results: List[Dict[str, Any]],
    catalog_id: str,
    images_provider: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
    save_groups: Optional[Callable[[str, List[Dict[str, Any]]], None]] = None,
) -> Dict[str, Any]:
    """Group images by similarity after hash computation.

    Args:
        results: Hash computation results
        catalog_id: The catalog UUID
        images_provider: Optional function to get images with hashes
        save_groups: Optional function to save duplicate groups

    Returns:
        Grouping results
    """
    from lumina.analysis.duplicates import group_by_exact_match, group_by_similarity

    # Get all images with hashes
    if images_provider:
        images = images_provider(catalog_id)
    else:
        # Default: use database lookup
        from lumina.db.models import Image
        from lumina.db.session import get_db_session

        with get_db_session() as session:
            db_images = (
                session.query(Image)
                .filter(Image.catalog_id == catalog_id)
                .filter(Image.dhash.isnot(None))
                .all()
            )
            images = [
                {
                    "id": str(img.id),
                    "checksum": img.checksum,
                    "dhash": img.dhash,
                    "ahash": img.ahash,
                    "whash": img.whash,
                }
                for img in db_images
            ]

    # Find exact duplicates
    exact_groups = group_by_exact_match(images)

    # Find perceptual duplicates (using dhash by default)
    perceptual_groups = group_by_similarity(images, hash_key="dhash", threshold=5)

    # Save to database if provider given
    all_groups = exact_groups + perceptual_groups
    if save_groups:
        save_groups(catalog_id, all_groups)

    return {
        "exact_groups": len(exact_groups),
        "perceptual_groups": len(perceptual_groups),
        "total_duplicates": sum(len(g["image_ids"]) for g in all_groups),
    }


# Register the duplicates job with the global registry
duplicates_job: ParallelJob[str] = register_job(
    ParallelJob(
        name="detect_duplicates",
        discover=discover_images_for_hashing,
        process=compute_image_hashes,
        finalize=finalize_duplicates,
        batch_size=1000,
        max_workers=4,
    )
)
