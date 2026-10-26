"""Where a request to the local API may come from (design doc 10.4.2): the Host
check against DNS rebinding, the Origin check against other sites."""

from fastapi.testclient import TestClient

from api.main import app

# Not as a context manager: the lifespan (the database check) isn't needed here.
client = TestClient(app, base_url="http://localhost:8000")


def test_the_app_itself_is_served():
    assert client.get("/health").status_code == 200
    assert client.get("/health", headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert TestClient(app, base_url="http://127.0.0.1:8000").get("/health").status_code == 200


def test_a_host_that_isnt_this_pc_is_refused():
    # A site whose DNS name was pointed at 127.0.0.1 sends its own name.
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400


def test_a_request_from_another_site_is_refused():
    for origin in ("https://evil.example", "null", "http://localhost:8080"):
        response = client.post("/novels", json={"title": "x"}, headers={"Origin": origin})
        assert response.status_code == 403
        assert client.delete("/novels/00000000-0000-0000-0000-000000000000", headers={"Origin": origin}).status_code == 403
