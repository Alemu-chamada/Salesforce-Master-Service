from __future__ import annotations


def test_app_starts(client):
    assert client is not None


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["app_env"] == "dev"
    assert "version" in data
    assert "components" in data


def test_stats_endpoint(client):
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["uptime_seconds"] >= 0
    assert "started_at" in data
    assert data["requests_total"] >= 1


def test_batch_info_route(client):
    response = client.get("/api/batch/info")
    assert response.status_code == 200
    data = response.json()
    assert "poll_interval_seconds" in data
    assert "max_wait_minutes" in data
    assert "supported_objects" in data
    assert "api_version" in data
    assert isinstance(data["supported_objects"], list)


def test_key_verify_route(client):
    response = client.get("/api/key/verify")
    assert response.status_code == 200
    data = response.json()
    assert "client_id" in data
    assert "role" in data
    assert data["signature_valid"] is True


def test_supported_objects_route(client):
    response = client.get("/api/normalization/supported-objects")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    object_names = {row["object_name"] for row in data}
    assert "Account" in object_names or "Opportunity" in object_names


def test_scan_list_route(client):
    response = client.get("/api/scan/list")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "pagination" in data
    assert data["items"] == []
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["total"] == 0


def test_scan_statistics_route(client):
    response = client.get("/api/scan/statistics")
    assert response.status_code == 200
    data = response.json()
    assert "counts_by_status" in data


def test_unimplemented_start_returns_501(client):
    payload = {
        "organization_id": "org-1",
        "salesforce_credentials": {"grant_type": "password"},
    }
    response = client.post("/api/scan/start", json=payload)
    assert response.status_code == 501


def test_validate_credentials_unimplemented(client):
    response = client.post(
        "/api/validate-credentials",
        json={"grant_type": "password"},
    )
    assert response.status_code == 501


def test_maintenance_unimplemented(client):
    r1 = client.post("/api/maintenance/cleanup?days_old=30")
    assert r1.status_code == 501
    r2 = client.post("/api/maintenance/detect-crashed?timeout_minutes=15")
    assert r2.status_code == 501
