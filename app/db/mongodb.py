from __future__ import annotations

import ssl
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings


class MongoDB:
    """
    Small connection manager for Motor.

    Why: keeps startup/shutdown logic in one place and avoids global client
    construction at import time (which can break tests and reload).
    """

    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("MongoDB not initialized. Call connect() on startup.")
        return self._db

    async def connect(self) -> None:
        settings = get_settings()
        import logging
        logger = logging.getLogger(__name__)
        
        # For MongoDB Atlas (mongodb+srv://), ensure proper SSL/TLS handling
        # Python 3.13 compatibility: use tlsAllowInvalidCertificates as workaround
        connection_options = {
            "serverSelectionTimeoutMS": 5000,  # Reduced to 5 seconds to fail faster
            "connectTimeoutMS": 5000,
        }
        
        # Check if it's an Atlas connection (mongodb+srv://)
        if "mongodb+srv://" in settings.mongodb_uri:
            # Ensure tlsAllowInvalidCertificates is in the URI (for Python 3.13 compatibility)
            uri = settings.mongodb_uri
            if "tlsAllowInvalidCertificates" not in uri:
                # Add the parameter if not present
                if "?" in uri:
                    uri += "&tlsAllowInvalidCertificates=true"
                else:
                    uri += "?tlsAllowInvalidCertificates=true"
        else:
            uri = settings.mongodb_uri
        
        # Create client - this is non-blocking, it just creates the client object
        # The actual connection happens lazily on first operation
        try:
            self._client = AsyncIOMotorClient(
                uri,
                **connection_options
            )
            # Set db reference immediately - this doesn't require a connection
            self._db = self._client[settings.mongodb_db]
            logger.info("MongoDB client initialized. Connection will be established on first operation.")
            
            # Try a quick ping test, but don't block if it fails
            # Use asyncio.wait_for to ensure we don't hang
            import asyncio
            try:
                await asyncio.wait_for(
                    self._client.admin.command('ping'),
                    timeout=3.0  # 3 second timeout for ping
                )
                logger.info("MongoDB connection test successful")
            except asyncio.TimeoutError:
                logger.warning("MongoDB ping timed out. Connection may work on first operation.")
            except Exception as e:
                logger.warning(f"MongoDB ping failed: {e}. Connection may work on first operation.")
                # Don't raise - allow server to start
        except Exception as e:
            logger.error(f"Failed to create MongoDB client: {e}")
            # Create a dummy client to prevent "not initialized" errors
            # This allows server to start, but DB operations will fail with better error messages
            raise RuntimeError(f"MongoDB client creation failed: {e}")

    async def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._db = None


mongodb = MongoDB()

