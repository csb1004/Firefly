from fastapi.testclient import TestClient

from bandi_cards.app import create_app


def test_health_endpoint():
    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
