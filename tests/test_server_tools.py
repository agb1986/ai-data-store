import itertools
from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId

from app import server

# @mcp.tool() wraps functions in FunctionTool objects; the plain coroutine is .fn
create_entry = server.create_entry.fn
list_entries = server.list_entries.fn
get_entry = server.get_entry.fn
update_entry = server.update_entry.fn
delete_entry = server.delete_entry.fn


@pytest.fixture(autouse=True)
def ticking_clock(monkeypatch):
    """Advance time 1ms per call — Mongo timestamps have millisecond precision,
    so real wall-clock time gives consecutive writes identical created_at."""
    base = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)
    ticks = itertools.count()

    class SteppingDatetime:
        @staticmethod
        def now(tz=None):
            return base + timedelta(milliseconds=next(ticks))

    monkeypatch.setattr(server, "datetime", SteppingDatetime)


async def test_create_entry_returns_formatted_doc():
    entry = await create_entry("finance-agent", "Verdict - MSFT", {"x": 1}, ["MSFT"])

    assert entry["source"] == "finance-agent"
    assert entry["description"] == "Verdict - MSFT"
    assert entry["keywords"] == ["MSFT"]
    assert entry["data"] == {"x": 1}
    assert entry["created_at"] == entry["updated_at"]
    assert ObjectId(entry["id"])


async def test_create_entry_defaults_keywords_to_empty_list():
    entry = await create_entry("a", "b", {})
    assert entry["keywords"] == []


async def test_list_entries_filters_and_sorts_newest_first():
    await create_entry("agent-a", "first", {}, ["MSFT"])
    await create_entry("agent-a", "second", {}, ["MSFT", "verdict"])
    await create_entry("agent-b", "other", {}, ["AAPL"])

    result = await list_entries()
    assert result["total"] == 3
    assert [i["description"] for i in result["items"]] == ["other", "second", "first"]

    by_source = await list_entries(source="agent-a")
    assert by_source["total"] == 2

    by_keywords = await list_entries(keywords=["MSFT", "verdict"])
    assert by_keywords["total"] == 1
    assert by_keywords["items"][0]["description"] == "second"


async def test_list_entries_pagination():
    for i in range(5):
        await create_entry("a", f"entry-{i}", {})

    page = await list_entries(limit=2, skip=2)
    assert page["total"] == 5
    assert len(page["items"]) == 2
    assert [i["description"] for i in page["items"]] == ["entry-2", "entry-1"]


async def test_list_entries_clamps_bad_limit_and_skip():
    await create_entry("a", "only", {})

    result = await list_entries(limit=-5, skip=-10)
    assert len(result["items"]) == 1

    result = await list_entries(limit=10_000_000)
    assert len(result["items"]) == 1


async def test_get_entry_roundtrip():
    created = await create_entry("a", "b", {"k": "v"})
    fetched = await get_entry(created["id"])
    assert fetched == created


async def test_get_entry_not_found():
    with pytest.raises(ValueError, match="Entry not found"):
        await get_entry(str(ObjectId()))


async def test_get_entry_invalid_id():
    with pytest.raises(ValueError, match="Invalid entry ID"):
        await get_entry("garbage")


async def test_update_entry_changes_only_given_fields():
    created = await create_entry("a", "old", {"k": "v"}, ["kw"])

    updated = await update_entry(created["id"], description="new")

    assert updated["description"] == "new"
    assert updated["source"] == "a"
    assert updated["keywords"] == ["kw"]
    assert updated["data"] == {"k": "v"}
    assert updated["updated_at"] > created["updated_at"]


async def test_update_entry_requires_a_field():
    created = await create_entry("a", "b", {})
    with pytest.raises(ValueError, match="No fields provided"):
        await update_entry(created["id"])


async def test_update_entry_not_found():
    with pytest.raises(ValueError, match="Entry not found"):
        await update_entry(str(ObjectId()), description="x")


async def test_delete_entry():
    created = await create_entry("a", "b", {})

    result = await delete_entry(created["id"])
    assert result == {"deleted": True, "id": created["id"]}

    with pytest.raises(ValueError, match="Entry not found"):
        await delete_entry(created["id"])
