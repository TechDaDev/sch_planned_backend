"""Shared pytest fixtures for the backend test suite."""

import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client() -> APIClient:
    """Return an unauthenticated DRF API client."""
    return APIClient()
