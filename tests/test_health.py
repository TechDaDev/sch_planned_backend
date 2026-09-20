"""Tests for the public health endpoint."""

HEALTH_URL = "/api/health/"


def test_health_returns_http_200(api_client):
    response = api_client.get(HEALTH_URL)

    assert response.status_code == 200


def test_health_returns_json(api_client):
    response = api_client.get(HEALTH_URL)

    assert response["Content-Type"] == "application/json"
    assert isinstance(response.json(), dict)


def test_health_reports_ok_status(api_client):
    response = api_client.get(HEALTH_URL)

    assert response.json()["status"] == "ok"


def test_health_reports_service_name(api_client):
    response = api_client.get(HEALTH_URL)

    assert response.json()["service"] == "sch_planner_backend"


def test_health_requires_no_authentication(api_client):
    response = api_client.get(HEALTH_URL)

    assert response.status_code not in (401, 403)
