import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_.-]{3,50}$')


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    email: Optional[str] = Field(None, max_length=254)

    @field_validator('username')
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not _USERNAME_RE.match(v):
            raise ValueError(
                'Username must be 3-50 characters and contain only letters, '
                'digits, underscores, dots, or hyphens.'
            )
        return v.lower()

    @field_validator('email')
    @classmethod
    def email_basic_check(cls, v: Optional[str]) -> Optional[str]:
        if v and '@' not in v:
            raise ValueError('Invalid email address.')
        return v.lower() if v else None


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator('username')
    @classmethod
    def lower_username(cls, v: str) -> str:
        return v.lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    role: str = ""


class UserResponse(BaseModel):
    """Safe user representation returned by the API (no password hash)."""
    username: str
    email: Optional[str] = None
    is_active: bool
    created_at: datetime


class UserInDB(BaseModel):
    """Internal model — stored in MongoDB."""
    username: str
    hashed_password: str
    email: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
