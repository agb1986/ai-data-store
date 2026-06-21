from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import uvicorn
from bson import ObjectId
from bson.errors import InvalidId
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.database import close_client, get_db


@asynccontextmanager
async def lifespan(server: FastMCP):
    yield
    await close_client()


mcp = FastMCP(
    "AI Data Store",
    description="Store and retrieve data results produced by AI agents.",
    lifespan=lifespan,
)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != settings.api_key:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


def _format(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    doc["created_at"] = doc["created_at"].isoformat()
    doc["updated_at"] = doc["updated_at"].isoformat()
    return doc


def _parse_id(entry_id: str) -> ObjectId:
    try:
        return ObjectId(entry_id)
    except (InvalidId, Exception):
        raise ValueError(f"Invalid entry ID: {entry_id}")


@mcp.tool()
async def create_entry(
    source: str,
    description: str,
    data: dict[str, Any],
    keywords: list[str] = [],
) -> dict:
    """Store a new data entry produced by an AI agent."""
    db = get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "source": source,
        "description": description,
        "keywords": keywords,
        "data": data,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.entries.insert_one(doc)
    created = await db.entries.find_one({"_id": result.inserted_id})
    return _format(created)


@mcp.tool()
async def list_entries(
    source: str | None = None,
    keywords: list[str] | None = None,
    limit: int = 20,
    skip: int = 0,
) -> dict:
    """List stored entries. Optionally filter by source agent or keywords."""
    db = get_db()
    query: dict = {}
    if source:
        query["source"] = source
    if keywords:
        query["keywords"] = {"$all": keywords}

    total = await db.entries.count_documents(query)
    cursor = db.entries.find(query).sort("created_at", -1).skip(skip).limit(limit)
    items = [_format(doc) async for doc in cursor]
    return {"total": total, "items": items}


@mcp.tool()
async def get_entry(entry_id: str) -> dict:
    """Retrieve a single entry by its ID."""
    db = get_db()
    doc = await db.entries.find_one({"_id": _parse_id(entry_id)})
    if not doc:
        raise ValueError(f"Entry not found: {entry_id}")
    return _format(doc)


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
    updates["updated_at"] = datetime.now(timezone.utc)
    result = await db.entries.find_one_and_update(
        {"_id": _parse_id(entry_id)},
        {"$set": updates},
        return_document=True,
    )
    if not result:
        raise ValueError(f"Entry not found: {entry_id}")
    return _format(result)


@mcp.tool()
async def delete_entry(entry_id: str) -> dict:
    """Delete an entry by its ID."""
    db = get_db()
    result = await db.entries.delete_one({"_id": _parse_id(entry_id)})
    if result.deleted_count == 0:
        raise ValueError(f"Entry not found: {entry_id}")
    return {"deleted": True, "id": entry_id}


if __name__ == "__main__":
    app = mcp.http_app(transport="sse")
    app.add_middleware(BearerAuthMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=8742)
