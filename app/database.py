from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_db():
    return get_client()[settings.mongodb_db]


async def ensure_indexes():
    db = get_db()
    await db.entries.create_index([("created_at", -1)])
    await db.entries.create_index("source")
    await db.entries.create_index("keywords")


async def close_client():
    global _client
    if _client is not None:
        _client.close()
        _client = None
