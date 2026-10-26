"""Who may use the local API (design doc 10.4.2): the Host check against DNS
rebinding, the client header against other sites."""

from fastapi.testclient import TestClient

from api.main import CLIENT_HEADER, app

# Not as a context manager: the lifespan (the database check) isn't needed here.
client = TestClient(app, base_url="http://localhost:8000")
APP = {CLIENT_HEADER: "1"}
MISSING = "00000000-0000-0000-0000-000000000000"


def test_the_app_itself_is_served():
    assert client.get("/health").status_code == 200
    # Past the checks to the router (a path with no route: 404, where the checks would answer 403).
    assert client.get("/no-such-route", headers=APP).status_code == 404
    assert client.get("/no-such-route").status_code == 403
    assert TestClient(app, base_url="http://127.0.0.1:8000").get("/health").status_code == 200


def test_a_host_that_isnt_this_pc_is_refused():
    # A site whose DNS name was pointed at 127.0.0.1 sends its own name.
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/no-such-route", headers={"Host": "evil.example", **APP}).status_code == 400


def test_a_request_without_the_client_header_is_refused():
    # What another site can send: a form post, an <img> GET (which can have side
    # effects, e.g. pending-links putting back stale picks), any Origin or none.
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "http://localhost:5173"}):
        assert client.post("/novels", json={"title": "x"}, headers=headers).status_code == 403
        assert client.get(f"/novels/{MISSING}/episodes/{MISSING}/pending-links", headers=headers).status_code == 403
        assert client.delete(f"/novels/{MISSING}", headers=headers).status_code == 403
