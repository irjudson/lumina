"""Pure functions for burst sequence detection.

Detects groups of images taken in rapid succession (bursts) based on
timestamps and camera metadata. Pure algorithmic approach - no ML.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


def detect_bursts(
    images: List[Dict[str, Any]],
    gap_threshold: float = 1.0,
    min_size: int = 3,
    min_duration: float = 0.5,
) -> List[Dict[str, Any]]:
    """Detect burst sequences in a list of images.

    A burst is defined as:
    - Images from the same camera
    - Taken within gap_threshold seconds of each other
    - At least min_size images
    - Total duration >= min_duration

    Args:
        images: List of image dicts with timestamp, camera fields
        gap_threshold: Maximum seconds between consecutive images
        min_size: Minimum images to form a burst
        min_duration: Minimum total duration in seconds

    Returns:
        List of burst dicts with image_ids, start_time, end_time, duration
    """
    if len(images) < min_size:
        return []

    # Group by camera
    by_camera: Dict[str, List[Dict[str, Any]]] = {}
    for img in images:
        camera = img.get("camera") or "unknown"
        if camera not in by_camera:
            by_camera[camera] = []
        by_camera[camera].append(img)

    all_bursts = []

    for _camera, camera_images in by_camera.items():
        # Sort by timestamp
        sorted_imgs = sorted(
            camera_images,
            key=lambda x: x.get("timestamp") or datetime.min,
        )

        # Find sequences
        bursts = _find_sequences(sorted_imgs, gap_threshold, min_size, min_duration)
        all_bursts.extend(bursts)

    return all_bursts


def _find_sequences(
    sorted_images: List[Dict[str, Any]],
    gap_threshold: float,
    min_size: int,
    min_duration: float,
) -> List[Dict[str, Any]]:
    """Find burst sequences in time-sorted images."""
    if len(sorted_images) < min_size:
        return []

    bursts = []
    current: List[Dict[str, Any]] = [sorted_images[0]]

    for i in range(1, len(sorted_images)):
        curr_img = sorted_images[i]
        prev_img = sorted_images[i - 1]

        curr_ts = curr_img.get("timestamp")
        prev_ts = prev_img.get("timestamp")

        if curr_ts and prev_ts:
            gap = (curr_ts - prev_ts).total_seconds()
        else:
            gap = float("inf")

        if gap <= gap_threshold:
            current.append(curr_img)
        else:
            # End of sequence - check if it's a valid burst
            if len(current) >= min_size:
                burst = _make_burst(current, min_duration)
                if burst:
                    bursts.append(burst)
            current = [curr_img]

    # Check final sequence
    if len(current) >= min_size:
        burst = _make_burst(current, min_duration)
        if burst:
            bursts.append(burst)

    return bursts


def _make_burst(
    images: List[Dict[str, Any]],
    min_duration: float,
) -> Optional[Dict[str, Any]]:
    """Create a burst dict if it meets duration requirement."""
    if len(images) < 2:
        return None

    timestamps: List[datetime] = [
        img["timestamp"] for img in images if img.get("timestamp") is not None
    ]
    if len(timestamps) < 2:
        return None

    start = min(timestamps)
    end = max(timestamps)
    duration = (end - start).total_seconds()

    if duration < min_duration:
        return None

    return {
        "image_ids": [img["id"] for img in images],
        "start_time": start,
        "end_time": end,
        "duration_seconds": duration,
        "camera": images[0].get("camera"),
    }


def select_best_in_burst(
    images: List[Dict[str, Any]],
    method: str = "quality",
) -> str:
    """Select the best image from a burst.

    Args:
        images: List of image dicts
        method: Selection method (quality, first, middle)

    Returns:
        ID of the best image
    """
    if not images:
        raise ValueError("Cannot select from empty list")

    if method == "first":
        return images[0]["id"]
    elif method == "middle":
        return images[len(images) // 2]["id"]
    else:  # quality
        best = max(images, key=lambda x: x.get("quality_score") or 0)
        return best["id"]
