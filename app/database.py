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


async def close_client():
    global _client
    if _client is not None:
        _client.close()
        _client = None
