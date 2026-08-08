import os

os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("UI_USERNAME", "admin")
os.environ.setdefault("UI_PASSWORD", "test-password")

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import database


@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    """Back every test with a fresh in-memory MongoDB."""
    client = AsyncMongoMockClient()
    monkeypatch.setattr(database, "_client", client)
    yield database.get_db()
