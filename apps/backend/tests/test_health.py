import pytest
from fastapi.testclient import TestClient
from ithutecode_api.main import create_app
from ithutecode_api.settings import Settings

def test_liveness():
    with TestClient(create_app(Settings("test"))) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "alive", "service": "ithutecode-api"}

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_production_documentation_disabled(path):
    with TestClient(create_app(Settings("production"))) as client:
        assert client.get(path).status_code == 404

def test_invalid_environment():
    with pytest.raises(ValueError):
        Settings("unknown")

def test_environment_configuration(monkeypatch):
    monkeypatch.setenv("ITHUTECODE_ENVIRONMENT", "staging")
    assert Settings.from_env().environment == "staging"
