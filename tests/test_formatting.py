from datetime import UTC, datetime

import pytest
from bson import ObjectId

from app.formatting import format_doc, parse_id


def test_format_doc_converts_id_and_timestamps():
    oid = ObjectId()
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    doc = {"_id": oid, "source": "x", "created_at": now, "updated_at": now}

    out = format_doc(doc)

    assert out["id"] == str(oid)
    assert "_id" not in out
    assert out["created_at"] == "2026-08-01T12:00:00+00:00"
    assert out["updated_at"] == "2026-08-01T12:00:00+00:00"


def test_format_doc_does_not_mutate_input():
    doc = {
        "_id": ObjectId(),
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    format_doc(doc)
    assert "_id" in doc


def test_parse_id_roundtrip():
    oid = ObjectId()
    assert parse_id(str(oid)) == oid


@pytest.mark.parametrize("bad", ["not-an-id", "", "68571a2c", 123])
def test_parse_id_invalid_raises_value_error(bad):
    with pytest.raises(ValueError, match="Invalid entry ID"):
        parse_id(bad)
