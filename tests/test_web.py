from datetime import UTC, datetime

import httpx
import pytest
from bson import ObjectId

from app.web import app as web_app

AUTH = ("admin", "test-password")


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=web_app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def seed(db, **overrides):
    now = datetime.now(UTC)
    doc = {
        "source": "finance-agent",
        "description": "Verdict - MSFT",
        "keywords": ["MSFT", "verdict"],
        "data": {"winner": "bear"},
        "created_at": now,
        "updated_at": now,
        **overrides,
    }
    result = await db.entries.insert_one(doc)
    return str(result.inserted_id)


async def test_requires_auth(client):
    resp = await client.get("/")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == 'Basic realm="ai-data-store"'


async def test_rejects_wrong_password(client):
    resp = await client.get("/", auth=("admin", "wrong"))
    assert resp.status_code == 401


async def test_index_empty_state(client):
    resp = await client.get("/", auth=AUTH)
    assert resp.status_code == 200
    assert "No entries found" in resp.text


async def test_index_lists_entries(client, mock_db):
    await seed(mock_db)
    await seed(mock_db, source="other-agent", description="Something else", keywords=[])

    resp = await client.get("/", auth=AUTH)
    assert resp.status_code == 200
    assert "Verdict - MSFT" in resp.text
    assert "Something else" in resp.text
    assert "2 entries" in resp.text


async def test_index_filters_by_source(client, mock_db):
    await seed(mock_db)
    await seed(mock_db, source="other-agent", description="Something else")

    resp = await client.get("/", params={"source": "other-agent"}, auth=AUTH)
    assert "Something else" in resp.text
    assert "Verdict - MSFT" not in resp.text


async def test_index_escapes_html(client, mock_db):
    await seed(mock_db, description="<script>alert(1)</script>")

    resp = await client.get("/", auth=AUTH)
    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


async def test_detail_page(client, mock_db):
    entry_id = await seed(mock_db)

    resp = await client.get(f"/entries/{entry_id}", auth=AUTH)
    assert resp.status_code == 200
    assert "Verdict - MSFT" in resp.text
    assert "winner" in resp.text
    assert entry_id in resp.text


@pytest.mark.parametrize("entry_id", ["garbage", str(ObjectId())])
async def test_detail_not_found(client, entry_id):
    resp = await client.get(f"/entries/{entry_id}", auth=AUTH)
    assert resp.status_code == 404
    assert "Entry not found" in resp.text
