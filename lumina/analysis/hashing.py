"""Pure functions for perceptual hashing.

These functions compute perceptual hashes for images without any
orchestration, progress tracking, or database access. They are
designed to be called by the job framework.

Hash types:
- dHash (difference hash): Gradient-based, good for crops/resizes
- aHash (average hash): Mean-based, simple but effective
- wHash (wavelet hash): DWT-based, most robust to transformations
"""

from pathlib import Path
from typing import Dict, Union

import numpy as np
import pywt
from PIL import Image


def hamming_distance(hash1: str, hash2: str) -> int:
    """Compute Hamming distance between two hex hashes.

    Args:
        hash1: First hash as hex string
        hash2: Second hash as hex string

    Returns:
        Number of differing bits

    Raises:
        ValueError: If hash lengths don't match
    """
    if len(hash1) != len(hash2):
        raise ValueError(f"Hash length mismatch: {len(hash1)} vs {len(hash2)}")

    # Convert hex to int and XOR
    diff = int(hash1, 16) ^ int(hash2, 16)
    return bin(diff).count("1")


def compute_dhash(image_path: Union[Path, str], hash_size: int = 8) -> str:
    """Compute difference hash (gradient-based).

    dHash computes a hash based on the difference between adjacent pixels.
    It's robust to scaling and aspect ratio changes.

    Args:
        image_path: Path to image file
        hash_size: Size of hash grid (default 8 = 64-bit hash)

    Returns:
        Hash as hex string (16 characters for 64-bit hash)
    """
    with Image.open(image_path) as img:
        # Convert to grayscale and resize
        img = img.convert("L")
        img = img.resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)

        pixels = list(img.getdata())

        # Compute differences - each bit is 1 if left pixel > right pixel
        bits = []
        for row in range(hash_size):
            for col in range(hash_size):
                left = pixels[row * (hash_size + 1) + col]
                right = pixels[row * (hash_size + 1) + col + 1]
                bits.append(1 if left > right else 0)

        # Convert to hex
        hash_int = int("".join(str(b) for b in bits), 2)
        return format(hash_int, f"0{hash_size * hash_size // 4}x")


def compute_ahash(image_path: Union[Path, str], hash_size: int = 8) -> str:
    """Compute average hash (mean-based).

    aHash computes a hash based on whether each pixel is above or below
    the average pixel value. Simple but effective for many use cases.

    Args:
        image_path: Path to image file
        hash_size: Size of hash grid (default 8 = 64-bit hash)

    Returns:
        Hash as hex string (16 characters for 64-bit hash)
    """
    with Image.open(image_path) as img:
        img = img.convert("L")
        img = img.resize((hash_size, hash_size), Image.Resampling.LANCZOS)

        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)

        bits = [1 if p > avg else 0 for p in pixels]
        hash_int = int("".join(str(b) for b in bits), 2)
        return format(hash_int, f"0{hash_size * hash_size // 4}x")


def compute_whash(image_path: Union[Path, str], hash_size: int = 8) -> str:
    """Compute wavelet hash (DWT-based).

    wHash uses discrete wavelet transform to compute a hash that is
    most robust to transformations like rotation, scaling, and compression.

    Args:
        image_path: Path to image file
        hash_size: Size of hash grid (default 8 = 64-bit hash)

    Returns:
        Hash as hex string (16 characters for 64-bit hash)
    """
    with Image.open(image_path) as img:
        img = img.convert("L")
        # Resize to power of 2 for DWT
        img = img.resize((hash_size * 4, hash_size * 4), Image.Resampling.LANCZOS)

        pixels = np.array(img, dtype=np.float64)

        # Apply 2D DWT with Haar wavelet
        coeffs = pywt.dwt2(pixels, "haar")
        cA, (cH, cV, cD) = coeffs

        # Resize approximation coefficients to hash_size
        cA_resized = Image.fromarray(cA).resize(
            (hash_size, hash_size), Image.Resampling.LANCZOS
        )
        cA_array = np.array(cA_resized)

        # Threshold by median
        median = np.median(cA_array)
        bits = (cA_array > median).flatten().astype(int)

        hash_int = int("".join(str(b) for b in bits), 2)
        return format(hash_int, f"0{hash_size * hash_size // 4}x")


def compute_all_hashes(
    image_path: Union[Path, str],
    hash_size: int = 8,
) -> Dict[str, str]:
    """Compute all three hash types for an image.

    Args:
        image_path: Path to image file
        hash_size: Size of hash grid (default 8 = 64-bit hashes)

    Returns:
        Dict with keys: dhash, ahash, whash
    """
    return {
        "dhash": compute_dhash(image_path, hash_size),
        "ahash": compute_ahash(image_path, hash_size),
        "whash": compute_whash(image_path, hash_size),
    }


def similarity_score(hash1: str, hash2: str, hash_bits: int = 64) -> int:
    """Compute similarity percentage between two hashes.

    Args:
        hash1: First hash as hex string
        hash2: Second hash as hex string
        hash_bits: Total bits in hash (default 64 for 8x8 grid)

    Returns:
        Similarity as percentage 0-100 (100 = identical)
    """
    distance = hamming_distance(hash1, hash2)
    return int(100 * (1 - distance / hash_bits))
