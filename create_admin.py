"""
Script to create an admin user.

Usage:
    python create_admin.py <email> <password> [full_name]
"""

import asyncio
import sys
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.core.security import hash_password
from app.repositories.user_repository import UserRepository


async def create_admin(email: str, password: str, full_name: str = None):
    """Create an admin user."""
    settings = get_settings()
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongodb_db]
    
    try:
        user_repo = UserRepository(db)
        
        # Check if user already exists
        existing_user = await user_repo.get_by_email(email)
        if existing_user:
            print(f"[INFO] User with email {email} already exists.")
            print(f"[INFO] Updating user to admin role...")
            
            # Update to admin
            from bson import ObjectId
            from datetime import datetime, timezone
            update_data = {"role": "admin"}
            update_data["updated_at"] = datetime.now(timezone.utc)
            
            await user_repo.collection.update_one(
                {"_id": ObjectId(existing_user.id)},
                {"$set": update_data}
            )
            
            print(f"[SUCCESS] User {email} is now an admin!")
            return
        
        # Create new admin user
        print(f"[INFO] Creating admin user: {email}")
        hashed_password = hash_password(password)
        
        user = await user_repo.create_user(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            role="admin",
        )
        
        print(f"[SUCCESS] Admin user created successfully!")
        print(f"  - ID: {user.id}")
        print(f"  - Email: {user.email}")
        print(f"  - Full Name: {user.full_name}")
        print(f"  - Role: {user.role}")
        
    except Exception as e:
        print(f"[ERROR] Failed to create admin user: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python create_admin.py <email> <password> [full_name]")
        print("\nExample:")
        print("  python create_admin.py admin@bvonix.academy Admin123! \"Admin User\"")
        sys.exit(1)
    
    email = sys.argv[1]
    password = sys.argv[2]
    full_name = sys.argv[3] if len(sys.argv) > 3 else None
    
    asyncio.run(create_admin(email, password, full_name))
