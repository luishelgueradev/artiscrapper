"""
Health endpoint test stubs — xfail until plan 02-03 (Wave 3).
OBS-01: GET /health. OBS-02: GET /health/deep.
"""
import pytest


@pytest.mark.xfail(strict=False, reason="Wave 3: test_health_shape filled by plan 02-03")
def test_health_shape():
    """OBS-01: GET /health returns 200 with {status, cloak, cache} fields."""
    pytest.skip("Wave 3: filled by plan 02-03")


@pytest.mark.xfail(strict=False, reason="Wave 3: test_health_deep_shape filled by plan 02-03")
def test_health_deep_shape():
    """OBS-02: GET /health/deep returns cloak and llm status fields."""
    pytest.skip("Wave 3: filled by plan 02-03")
