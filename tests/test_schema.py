"""Tests for the OpenAPI schema and Swagger UI endpoints."""

SCHEMA_URL = "/api/schema/"
DOCS_URL = "/api/docs/"


def test_schema_endpoint_is_reachable(api_client):
    response = api_client.get(SCHEMA_URL)

    assert response.status_code == 200
    assert response.content


def test_schema_reports_api_metadata(api_client):
    response = api_client.get(SCHEMA_URL, {"format": "json"})

    assert response.status_code == 200
    info = response.json()["info"]
    assert info["title"] == "College Academic Schedule Planner API"
    assert info["version"] == "0.1.0"


def test_schema_documents_health_endpoint(api_client):
    response = api_client.get(SCHEMA_URL, {"format": "json"})

    assert "get" in response.json()["paths"]["/api/health/"]


def test_docs_endpoint_serves_swagger_ui(api_client):
    response = api_client.get(DOCS_URL)

    assert response.status_code == 200
    assert "text/html" in response["Content-Type"]
