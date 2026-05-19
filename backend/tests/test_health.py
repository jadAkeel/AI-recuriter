from fastapi.testclient import TestClient

from app.main import create_app


def test_health() -> None:
    """
    Checks that health.
    """
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
