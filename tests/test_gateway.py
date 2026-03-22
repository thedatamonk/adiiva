# tests/test_gateway.py
import pytest
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.app import app
    return TestClient(app)


def test_connect_missing_auth(client):
    """POST /connect without Authorization header returns 401."""
    resp = client.post("/connect")
    assert resp.status_code == 401


def test_connect_invalid_token(client):
    """POST /connect with bad JWT returns 401."""
    resp = client.post("/connect", headers={"Authorization": "Bearer bad-token"})
    assert resp.status_code == 401


@patch("src.app.subprocess.Popen")
@patch("src.app.get_next_port", new_callable=AsyncMock, return_value=9001)
@patch("src.app.acquire_session_slot", new_callable=AsyncMock, return_value=True)
@patch("src.app.wait_for_worker_ready", new_callable=AsyncMock, return_value=True)
def test_connect_success(mock_wait, mock_acquire, mock_port, mock_popen, client):
    """POST /connect with valid JWT returns worker_url."""
    from src.auth import create_token
    token = create_token("alice")
    resp = client.post("/connect", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "worker_url" in data
    assert "session_id" in data
    assert "9001" in data["worker_url"]
    mock_popen.assert_called_once()


@patch("src.app.acquire_session_slot", new_callable=AsyncMock, return_value=False)
def test_connect_rate_limited(mock_acquire, client):
    """POST /connect when rate limited returns 429."""
    from src.auth import create_token
    token = create_token("alice")
    resp = client.post("/connect", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 429
