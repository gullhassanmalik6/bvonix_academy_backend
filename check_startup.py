"""Check what's preventing server startup."""
import sys
import asyncio

print("Checking imports...")
try:
    from app.core.config import get_settings
    print("[OK] Config imported")
except Exception as e:
    print(f"[ERROR] Config import failed: {e}")
    sys.exit(1)

try:
    from app.db.mongodb import mongodb
    print("[OK] MongoDB module imported")
except Exception as e:
    print(f"[ERROR] MongoDB import failed: {e}")
    sys.exit(1)

print("\nChecking settings...")
try:
    settings = get_settings()
    print("[OK] Settings loaded")
    print(f"   MongoDB URI: {settings.mongodb_uri[:30]}...")
    print(f"   MongoDB DB: {settings.mongodb_db}")
except Exception as e:
    print(f"[ERROR] Settings failed: {e}")
    sys.exit(1)

print("\nTesting MongoDB connection...")
async def test_mongo():
    try:
        await mongodb.connect()
        print("[OK] MongoDB connected")
        await mongodb.disconnect()
        print("[OK] MongoDB disconnected")
    except Exception as e:
        print(f"[ERROR] MongoDB connection failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

try:
    asyncio.run(test_mongo())
except Exception as e:
    print(f"[ERROR] Async test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n[SUCCESS] All checks passed! Server should start now.")
