from datetime import datetime
from typing import Optional

from loguru import logger
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from workflows.core.settings import config_settings
from workflows.auth.models import UserInDB

_client: Optional[AsyncIOMotorClient] = None
_collection: Optional[AsyncIOMotorCollection] = None


async def init_auth_db() -> None:
    """Connect to MongoDB and ensure required indexes exist."""
    global _client, _collection

    _client = AsyncIOMotorClient(
        config_settings.MONGO_AUTH_URI,
        serverSelectionTimeoutMS=5000,
    )
    db = _client[config_settings.MONGO_AUTH_DATABASE]
    _collection = db[config_settings.MONGO_AUTH_COLLECTION]

    # Unique index on username
    await _collection.create_index("username", unique=True)
    # Sparse unique index on email (allows multiple docs without email)
    await _collection.create_index("email", unique=True, sparse=True)

    # Verify connectivity
    await _client.admin.command("ping")
    logger.info(
        f"[AUTH DB] Connected to MongoDB  "
        f"db={config_settings.MONGO_AUTH_DATABASE}  "
        f"collection={config_settings.MONGO_AUTH_COLLECTION}"
    )


async def close_auth_db() -> None:
    """Close the MongoDB connection."""
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("[AUTH DB] MongoDB connection closed")


def _get_collection() -> AsyncIOMotorCollection:
    if _collection is None:
        raise RuntimeError(
            "Auth database is not initialized. "
            "Ensure init_auth_db() is called at application startup."
        )
    return _collection


async def get_user_by_username(username: str) -> Optional[UserInDB]:
    """Return a UserInDB or None if not found."""
    doc = await _get_collection().find_one({"username": username})
    if doc is None:
        return None
    doc.pop("_id", None)
    return UserInDB(**doc)


async def username_exists(username: str) -> bool:
    count = await _get_collection().count_documents({"username": username}, limit=1)
    return count > 0


async def email_exists(email: str) -> bool:
    count = await _get_collection().count_documents({"email": email}, limit=1)
    return count > 0


async def create_user(user: UserInDB) -> None:
    """Insert a new user document. Raises DuplicateKeyError if username/email exists."""
    await _get_collection().insert_one(user.model_dump())
    logger.info(f"[AUTH DB] Created user username='{user.username}'")


async def deactivate_user(username: str) -> bool:
    """Soft-delete: set is_active=False. Returns True if user was found."""
    result = await _get_collection().update_one(
        {"username": username},
        {"$set": {"is_active": False}},
    )
    return result.matched_count > 0
