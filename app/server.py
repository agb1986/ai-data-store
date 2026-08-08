import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastmcp import FastMCP
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.database import close_client, ensure_indexes, get_db
from app.formatting import format_doc, parse_id

MAX_LIMIT = 100


@asynccontextmanager
async def lifespan(server: FastMCP):
    await ensure_indexes()
    yield
    await close_client()


mcp = FastMCP("AI Data Store", lifespan=lifespan)


class BearerAuthMiddleware:
    """Pure ASGI middleware — does not buffer the response, safe for SSE streaming."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            token = auth[7:] if auth.startswith("Bearer ") else ""
            if not secrets.compare_digest(token.encode(), settings.api_key.encode()):
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def _create_entry(
    source: str,
    description: str,
    data: dict[str, Any],
    keywords: list[str] | None = None,
) -> dict:
    db = get_db()
    now = datetime.now(UTC)
    doc = {
        "source": source,
        "description": description,
        "keywords": keywords or [],
        "data": data,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.entries.insert_one(doc)
    created = await db.entries.find_one({"_id": result.inserted_id})
    return format_doc(created)


@mcp.tool()
async def create_entry(
    source: str,
    description: str,
    data: dict[str, Any],
    keywords: list[str] | None = None,
) -> dict:
    """Store a new data entry produced by an AI agent."""
    return await _create_entry(source, description, data, keywords)


@mcp.tool()
async def list_entries(
    source: str | None = None,
    keywords: list[str] | None = None,
    limit: int = 20,
    skip: int = 0,
) -> dict:
    """List stored entries. Optionally filter by source agent or keywords."""
    limit = max(1, min(limit, MAX_LIMIT))
    skip = max(0, skip)
    db = get_db()
    query: dict = {}
    if source:
        query["source"] = source
    if keywords:
        query["keywords"] = {"$all": keywords}

    total = await db.entries.count_documents(query)
    cursor = db.entries.find(query).sort("created_at", -1).skip(skip).limit(limit)
    items = [format_doc(doc) async for doc in cursor]
    return {"total": total, "items": items}


@mcp.tool()
async def get_entry(entry_id: str) -> dict:
    """Retrieve a single entry by its ID."""
    db = get_db()
    doc = await db.entries.find_one({"_id": parse_id(entry_id)})
    if not doc:
        raise ValueError(f"Entry not found: {entry_id}")
    return format_doc(doc)


@mcp.tool()
async def update_entry(
    entry_id: str,
    source: str | None = None,
    description: str | None = None,
    keywords: list[str] | None = None,
    data: dict[str, Any] | None = None,
) -> dict:
    """Update an existing entry. Only the provided fields are changed."""
    updates = {
        k: v for k, v in {
            "source": source,
            "description": description,
            "keywords": keywords,
            "data": data,
        }.items() if v is not None
    }
    if not updates:
        raise ValueError("No fields provided to update")
    db = get_db()
    updates["updated_at"] = datetime.now(UTC)
    result = await db.entries.find_one_and_update(
        {"_id": parse_id(entry_id)},
        {"$set": updates},
        return_document=True,
    )
    if not result:
        raise ValueError(f"Entry not found: {entry_id}")
    return format_doc(result)


@mcp.tool()
async def delete_entry(entry_id: str) -> dict:
    """Delete an entry by its ID."""
    db = get_db()
    result = await db.entries.delete_one({"_id": parse_id(entry_id)})
    if result.deleted_count == 0:
        raise ValueError(f"Entry not found: {entry_id}")
    return {"deleted": True, "id": entry_id}


class EntryPayload(BaseModel):
    source: str
    description: str
    data: dict[str, Any]
    keywords: list[str] = []


async def create_entry_endpoint(request: Request) -> JSONResponse:
    """REST equivalent of create_entry, for callers that can't speak MCP (e.g. hook scripts)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    try:
        payload = EntryPayload.model_validate(body)
    except ValidationError as e:
        errors = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc']) or 'body'}: {err['msg']}"
            for err in e.errors()
        )
        return JSONResponse({"error": errors}, status_code=400)

    entry = await _create_entry(
        source=payload.source,
        description=payload.description,
        data=payload.data,
        keywords=payload.keywords,
    )
    return JSONResponse(entry, status_code=201)


if __name__ == "__main__":
    app = mcp.http_app(transport="sse")
    app.add_route("/entries", create_entry_endpoint, methods=["POST"])
    app.add_middleware(BearerAuthMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=8742)
