from app.main import app
from tests.api_client import get


def test_health() -> None:
    response = get(app, "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
