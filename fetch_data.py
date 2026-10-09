"""
Script to fetch and display data from MongoDB database.
Shows all collections and their documents.
"""
import asyncio
import json
from datetime import datetime
from typing import Any

from app.db.mongodb import mongodb
from app.core.config import get_settings


def format_datetime(dt: Any) -> str:
    """Format datetime for display."""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)


def format_document(doc: dict[str, Any], hide_sensitive: bool = True) -> dict[str, Any]:
    """Format document for display, hiding sensitive fields."""
    formatted = {}
    for key, value in doc.items():
        if key == "_id":
            formatted["id"] = str(value)
        elif key == "hashed_password" and hide_sensitive:
            formatted[key] = "***hidden***"
        elif isinstance(value, datetime):
            formatted[key] = format_datetime(value)
        elif isinstance(value, dict):
            formatted[key] = format_document(value, hide_sensitive)
        elif isinstance(value, list):
            formatted[key] = [
                format_document(item, hide_sensitive) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            formatted[key] = value
    return formatted


async def stream_collection(collection_name: str, batch_size: int = 100):
    """Yield every document in bounded batches and return the printed count."""
    collection = mongodb.db[collection_name]
    expected = await collection.count_documents({})
    printed = 0
    skip = 0
    while skip < expected:
        batch = await (
            collection.find({})
            .sort([("_id", 1)])
            .skip(skip)
            .limit(batch_size)
            .to_list(length=batch_size)
        )
        if not batch:
            break
        for document in batch:
            printed += 1
            formatted = format_document(document)
            print(f"  Document {printed}:")
            print(f"  {json.dumps(formatted, indent=4, default=str)}")
            print()
        skip += len(batch)
    if printed != expected:
        raise RuntimeError(
            f"{collection_name} exported {printed} document(s) but the collection count is {expected}"
        )
    return printed


async def main():
    """Main function to fetch and display all database data."""
    settings = get_settings()
    
    print("=" * 80)
    print("FETCHING DATA FROM MONGODB DATABASE")
    print("=" * 80)
    print(f"Database: {settings.mongodb_db}")
    print("=" * 80)
    print()
    
    # Connect to MongoDB
    try:
        await mongodb.connect()
        print("[OK] Connected to MongoDB\n")
    except Exception as e:
        print(f"[ERROR] Failed to connect to MongoDB: {e}")
        raise SystemExit(1) from e
    
    # List of collections to fetch
    collections = [
        "users",
        "courses",
        "students",
        "instructors",
        "enrollments",
        "results",
        "attendances",  # Note: collection is plural
        "certificates",
    ]
    
    total_documents = 0

    try:
        for collection_name in collections:
            print(f"[COLLECTION] {collection_name}")
            print("-" * 80)

            count = await stream_collection(collection_name)
            total_documents += count

            if count == 0:
                print(f"  [WARNING] No documents found in '{collection_name}'")
            else:
                print(f"  [OK] Found {count} document(s)\n")

            print()

        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total documents across all collections: {total_documents}")
        print("=" * 80)

        print("\n[INFO] All collections in database:")
        all_collections = await mongodb.db.list_collection_names()
        for coll in sorted(all_collections):
            count = await mongodb.db[coll].count_documents({})
            print(f"  - {coll}: {count} document(s)")
    except Exception as e:
        print(f"\n[ERROR] Export failed: {e}")
        raise SystemExit(1) from e
    finally:
        await mongodb.disconnect()
        print("\n[OK] Disconnected from MongoDB")


if __name__ == "__main__":
    asyncio.run(main())
