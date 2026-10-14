from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from loguru import logger

from workflows.auth.models import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from workflows.auth.utils import create_access_token, verify_password, hash_password
from workflows.core.settings import config_settings

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Demo users (hardcoded for demo — no MongoDB dependency) ───────────────────
# Replace with DB-backed auth when MongoDB is available.
_DEMO_USERS = {
    "admin": {
        "hashed_password": hash_password("admin123"),
        "is_active": True,
        "email": "admin@shopmail.com",
        "created_at": datetime(2026, 1, 1),
    },
    "agent": {
        "hashed_password": hash_password("agent123"),
        "is_active": True,
        "email": "agent@shopmail.com",
        "created_at": datetime(2026, 1, 1),
    },
}


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(request: RegisterRequest) -> UserResponse:
    """Registration is disabled in demo mode — use hardcoded demo users."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Registration is disabled in demo mode. Use demo credentials to log in.",
    )


@router.post("/token", response_model=TokenResponse)
async def login(request: LoginRequest) -> TokenResponse:
    """Authenticate with demo credentials and receive a JWT bearer token."""
    invalid_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user = _DEMO_USERS.get(request.username.lower())
    if user is None:
        logger.warning(f"[AUTH] Failed login — unknown username='{request.username}'")
        raise invalid_exc

    if not verify_password(request.password, user["hashed_password"]):
        logger.warning(f"[AUTH] Failed login — wrong password for username='{request.username}'")
        raise invalid_exc

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    token = create_access_token(request.username.lower())
    expire_seconds = config_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    role = "admin" if request.username.lower() == "admin" else "agent"
    logger.info(f"[AUTH] Token issued for username='{request.username}' role='{role}'")
    return TokenResponse(access_token=token, expires_in=expire_seconds, role=role)
