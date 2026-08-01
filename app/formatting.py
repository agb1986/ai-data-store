from bson import ObjectId
from bson.errors import InvalidId


def format_doc(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    doc["created_at"] = doc["created_at"].isoformat()
    doc["updated_at"] = doc["updated_at"].isoformat()
    return doc


def parse_id(entry_id: str) -> ObjectId:
    try:
        return ObjectId(entry_id)
    except (InvalidId, Exception):
        raise ValueError(f"Invalid entry ID: {entry_id}")
