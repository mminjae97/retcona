"""Who may use the local API (design doc 10.4.2): the Host check against DNS
rebinding, the client header against other sites, no framing."""

from fastapi.routing import APIRoute
from fastapi.security import APIKeyHeader
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from api.main import CLIENT_HEADER, NoFramingMiddleware, app

# Not as a context manager: the lifespan (the database check) isn't needed here.
client = TestClient(app, base_url="http://localhost:8000")
APP = {CLIENT_HEADER: "1"}
MISSING = "00000000-0000-0000-0000-000000000000"


def test_the_app_itself_is_served():
    assert client.get("/health").status_code == 200
    assert TestClient(app, base_url="http://127.0.0.1:8000").get("/health").status_code == 200
    # IPv6 loopback, port and all (an older Starlette cut the host at the first ':').
    assert client.get("/health", headers={"Host": "[::1]:8000"}).status_code == 200
    # Past the header check to the route's own validation (422 for no title,
    # before any database work).
    assert client.post("/novels", json={}, headers=APP).status_code == 422


def test_a_host_that_isnt_this_pc_is_refused():
    # A site whose DNS name was pointed at 127.0.0.1 sends its own name.
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/novels", json={}, headers={"Host": "evil.example", **APP}).status_code == 400


def test_a_request_without_the_client_header_is_refused():
    # What another site can send: a form post, an <img> GET (which can have side
    # effects, e.g. pending-links putting back stale picks), any Origin or none.
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "http://localhost:5173"}):
        assert client.post("/novels", json={"title": "x"}, headers=headers).status_code in (401, 403)
        assert client.get(f"/novels/{MISSING}/episodes/{MISSING}/pending-links", headers=headers).status_code in (401, 403)
        assert client.delete(f"/novels/{MISSING}", headers=headers).status_code in (401, 403)


def test_a_route_added_later_needs_the_header_too():
    # The header is the app's own dependency, not each router's: every API route
    # gets it, one added later too.
    assert any(
        isinstance(dependency.dependency, APIKeyHeader) and dependency.dependency.model.name == CLIENT_HEADER
        for dependency in app.router.dependencies
    )
    for route in app.routes:
        if isinstance(route, APIRoute):
            assert any(isinstance(d.call, APIKeyHeader) for d in route.dependant.dependencies), route.path


def test_no_page_can_be_framed():
    for path, headers in (("/health", {}), ("/docs", {}), ("/health", {"Host": "evil.example"})):
        response = client.get(path, headers=headers)
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["content-security-policy"] == "frame-ancestors 'none'"


def test_a_page_setting_its_own_framing_headers_gets_ours_once():
    def page(request):
        return PlainTextResponse("", headers={"X-Frame-Options": "SAMEORIGIN", "Content-Security-Policy": "default-src 'self'"})

    inner = Starlette(routes=[Route("/", page)])
    response = TestClient(NoFramingMiddleware(inner)).get("/")
    assert response.headers.get_list("x-frame-options") == ["DENY"]
    assert response.headers.get_list("content-security-policy") == ["frame-ancestors 'none'"]


def test_the_docs_know_the_header():
    schema = client.get("/openapi.json").json()
    [scheme] = schema["components"]["securitySchemes"].values()
    assert (scheme["type"], scheme["in"], scheme["name"]) == ("apiKey", "header", CLIENT_HEADER)
