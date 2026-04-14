"""Basic smoke tests for duplicate review API endpoints."""

import requests

CATALOG_ID = "36ee8b6f-9bfc-4bcd-a0ad-3e5a26946886"
BASE = f"http://localhost:8765/api/catalogs/{CATALOG_ID}"


def test_stats_endpoint_returns_valid_structure():
    """Stats endpoint returns valid JSON for a real catalog."""
    r = requests.get(f"{BASE}/duplicates/stats")
    assert r.status_code == 200
    data = r.json()
    assert "by_layer" in data
    assert "thresholds" in data
    assert "suppressed_pairs" in data


def test_candidates_list_returns_valid_structure():
    """Candidates list endpoint returns paginated structure."""
    r = requests.get(f"{BASE}/duplicates/candidates")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "candidates" in data
    assert isinstance(data["candidates"], list)


def test_decide_endpoint_validates_input():
    """Decide endpoint returns 422 with invalid decision, not 404."""
    r = requests.post(
        f"{BASE}/duplicates/candidates/00000000-0000-0000-0000-000000000001/decide",
        json={"decision": "invalid_value"},
    )
    assert r.status_code == 422
