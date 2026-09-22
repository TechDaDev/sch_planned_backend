"""Tests for the OpenAPI schema and Swagger UI endpoints."""

SCHEMA_URL = "/api/schema/"
DOCS_URL = "/api/docs/"


def is_public_operation(operation):
    security = operation.get("security", [])
    return security in ([], [{}])


def test_schema_endpoint_is_reachable(api_client):
    response = api_client.get(SCHEMA_URL)

    assert response.status_code == 200
    assert response.content


def test_schema_reports_api_metadata(api_client):
    response = api_client.get(SCHEMA_URL, {"format": "json"})

    assert response.status_code == 200
    info = response.json()["info"]
    assert info["title"] == "College Academic Schedule Planner API"
    # Phase 17 promotes the schema to the release-candidate version.
    assert info["version"] == "1.0.0"


def test_schema_is_the_only_public_surface_besides_health_and_auth(api_client):
    """Route inventory: only health, login and refresh are unauthenticated.

    Any other endpoint that loses its authentication requirement is a release blocker, so
    the inventory is asserted rather than reviewed by eye.
    """
    response = api_client.get(SCHEMA_URL, {"format": "json"})
    paths = response.json()["paths"]

    public, protected = [], []
    for path, operations in paths.items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            target = public if is_public_operation(operation) else protected
            target.append(f"{method.upper()} {path}")

    assert sorted(public) == [
        "GET /api/health/",
        "GET /api/health/live/",
        "GET /api/health/ready/",
        "POST /api/auth/login/",
        "POST /api/auth/refresh/",
    ], sorted(public)
    assert len(protected) > 50, len(protected)


def test_schema_documents_health_endpoint(api_client):
    response = api_client.get(SCHEMA_URL, {"format": "json"})

    assert "get" in response.json()["paths"]["/api/health/"]


def test_schema_documents_phase_1_auth_and_me_endpoints(api_client):
    response = api_client.get(SCHEMA_URL, {"format": "json"})

    paths = response.json()["paths"]
    assert "post" in paths["/api/auth/login/"]
    assert "post" in paths["/api/auth/refresh/"]
    assert "get" in paths["/api/me/"]


def test_schema_marks_login_and_refresh_public_but_me_authenticated(api_client):
    response = api_client.get(SCHEMA_URL, {"format": "json"})

    paths = response.json()["paths"]
    assert is_public_operation(paths["/api/auth/login/"]["post"])
    assert is_public_operation(paths["/api/auth/refresh/"]["post"])
    assert paths["/api/me/"]["get"].get("security")


def test_docs_endpoint_serves_swagger_ui(api_client):
    response = api_client.get(DOCS_URL)

    assert response.status_code == 200
    assert "text/html" in response["Content-Type"]
