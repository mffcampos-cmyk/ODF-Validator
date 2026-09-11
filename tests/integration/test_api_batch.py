from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)
M = '<OdfBody CompetitionCode="SYOG2026" DocumentCode="ARC" DocumentType="DT_RESULT" Version="1" Date="d" Time="t" LogicalDate="d" FeedFlag="P" Source="S"><Competition><Discipline Code="ARC"/></Competition></OdfBody>'


def test_batch_two_files():
    files = [("files", ("a.xml", M, "text/xml")),
             ("files", ("b.xml", "<bad", "text/xml"))]
    r = client.post("/validate/batch", data={"pack": "SYOG26"}, files=files)
    assert r.status_code == 200
    body = r.json()
    assert set(body["files"]) == {"a.xml", "b.xml"}
    assert "totals" in body
