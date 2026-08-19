from __future__ import annotations

import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client():
    # Instantiated without the lifespan context so no camera or broker is touched.
    return TestClient(main.app)


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, api_token="s3cret"))


def test_healthz_is_public(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_builtin_model_is_always_listed(client):
    assert "mediapipe_hands" in client.get("/api/models").json()["models"]


def test_mqtt_password_is_never_returned(client):
    body = client.get("/api/mqtt").json()
    assert body["password"] in ("", "********")


def test_unknown_source_returns_404(client):
    assert client.get("/snapshot/nope.jpg").status_code == 404
    assert client.get("/stream/nope.mjpg").status_code == 404


@pytest.mark.parametrize("name", ["../../evil.pt", "sub/dir.pt"])
def test_model_names_cannot_escape_the_model_directory(client, name):
    response = client.post("/api/models/activate", json={"name": name})
    assert response.status_code == 400


def test_activating_a_missing_model_returns_404(client):
    assert client.post("/api/models/activate", json={"name": "nope.pt"}).status_code == 404


def test_only_pt_uploads_are_accepted(client):
    response = client.post(
        "/api/models/upload",
        files={"file": ("evil.sh", io.BytesIO(b"rm -rf /"), "application/octet-stream")},
    )
    assert response.status_code == 400


def test_oversized_uploads_are_rejected(client, monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, max_upload_mb=1))
    payload = io.BytesIO(b"\x00" * (2 * 1024 * 1024))
    response = client.post("/api/models/upload", files={"file": ("big.pt", payload, "application/octet-stream")})
    assert response.status_code == 413
    assert not (main.settings.model_dir / "big.pt").exists()
    assert not (main.settings.model_dir / "big.pt.part").exists()


def test_updating_a_missing_source_returns_404(client):
    assert client.put("/api/sources/ghost", json={"name": "x"}).status_code == 404
    assert client.delete("/api/sources/ghost").status_code == 404


def test_protected_routes_reject_requests_without_a_token(client, secured):
    assert client.get("/api/status").status_code == 401
    assert client.get("/snapshot/cam1.jpg").status_code == 401
    assert client.get("/healthz").status_code == 200


def test_bearer_header_is_accepted(client, secured):
    response = client.get("/api/status", headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 200


def test_query_token_is_accepted_for_media_urls(client, secured):
    assert client.get("/snapshot/cam1.jpg?token=s3cret").status_code == 404


def test_login_sets_a_cookie_that_authenticates_later_requests(client, secured):
    assert client.post("/api/login", json={"token": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"token": "s3cret"}).status_code == 200
    assert client.get("/api/status").status_code == 200


def test_auth_state_is_reported_to_the_ui(client, secured):
    assert client.get("/api/auth").json() == {"auth_required": True}
