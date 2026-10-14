from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from loguru import logger

from workflows.core.settings import config_settings


# ── JWT helpers ───────────────────────────────────────────────

def _get_secret() -> str:
    secret = config_settings.JWT_SECRET_KEY
    if not secret:
        raise RuntimeError(
            "JWT_SECRET_KEY is not configured. "
            "Set it in your .env file before starting the application."
        )
    return secret


def create_access_token(username: str) -> str:
    """Create a signed JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=config_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": username, "exp": expire, "type": "access"}
    return jwt.encode(payload, _get_secret(), algorithm=config_settings.JWT_ALGORITHM)


def verify_token(token: str) -> str | None:
    """Verify a JWT token and return the username (sub), or None if invalid/expired."""
    try:
        payload = jwt.decode(
            token,
            _get_secret(),
            algorithms=[config_settings.JWT_ALGORITHM],
        )
        if payload.get("type") != "access":
            return None
        username: str | None = payload.get("sub")
        return username or None
    except JWTError as exc:
        logger.warning(f"[AUTH] JWT verification failed: {exc}")
        return None


# ── Password helpers ──────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False
