from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "ODF Validator" in r.text
    assert "Export JSON" in r.text
