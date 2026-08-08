import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from app.server import BearerAuthMiddleware, create_entry_endpoint

VALID = {
    "source": "finance-agent",
    "description": "Verdict - MSFT",
    "keywords": ["MSFT", "verdict"],
    "data": {"winner": "bear"},
}
AUTH = {"Authorization": "Bearer test-api-key"}


@pytest.fixture
def client():
    app = Starlette(routes=[Route("/entries", create_entry_endpoint, methods=["POST"])])
    app.add_middleware(BearerAuthMiddleware)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_rejects_missing_token(client):
    resp = await client.post("/entries", json=VALID)
    assert resp.status_code == 401


async def test_rejects_wrong_token(client):
    resp = await client.post("/entries", json=VALID, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


async def test_rejects_non_bearer_scheme(client):
    resp = await client.post("/entries", json=VALID, headers={"Authorization": "test-api-key"})
    assert resp.status_code == 401


async def test_creates_entry(client):
    resp = await client.post("/entries", json=VALID, headers=AUTH)

    assert resp.status_code == 201
    entry = resp.json()
    assert entry["source"] == "finance-agent"
    assert entry["keywords"] == ["MSFT", "verdict"]
    assert entry["data"] == {"winner": "bear"}
    assert entry["id"]


async def test_keywords_optional(client):
    payload = {k: v for k, v in VALID.items() if k != "keywords"}
    resp = await client.post("/entries", json=payload, headers=AUTH)
    assert resp.status_code == 201
    assert resp.json()["keywords"] == []


async def test_rejects_invalid_json(client):
    resp = await client.post(
        "/entries", content=b"not json", headers={**AUTH, "Content-Type": "application/json"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid JSON body"


async def test_rejects_missing_field(client):
    payload = {k: v for k, v in VALID.items() if k != "description"}
    resp = await client.post("/entries", json=payload, headers=AUTH)
    assert resp.status_code == 400
    assert "description" in resp.json()["error"]


async def test_rejects_wrong_field_type(client):
    resp = await client.post("/entries", json={**VALID, "data": "not a dict"}, headers=AUTH)
    assert resp.status_code == 400
    assert "data" in resp.json()["error"]
