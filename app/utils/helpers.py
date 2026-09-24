from __future__ import annotations

from bson import ObjectId


def oid_str(oid: ObjectId) -> str:
    return str(oid)


def to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as e:  # noqa: BLE001
        raise ValueError("Invalid ObjectId") from e

