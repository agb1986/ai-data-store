from app import database


async def test_ensure_indexes_creates_expected_indexes(mock_db):
    await database.ensure_indexes()

    index_info = await mock_db.entries.index_information()
    indexed_keys = {tuple(info["key"]) for info in index_info.values()}
    assert (("created_at", -1),) in indexed_keys
    assert (("source", 1),) in indexed_keys
    assert (("keywords", 1),) in indexed_keys
