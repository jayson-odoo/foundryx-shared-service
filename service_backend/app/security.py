"""Password hashing and JWT issuance/verification.

FastAPI is the single source of truth for auth: it hashes passwords (bcrypt),
issues access tokens (JWT signed with settings.jwt_secret), and verifies them.
NextAuth on the frontend merely carries the token in its session.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings


# bcrypt only considers the first 72 bytes and raises on longer input (>=4.x).
# Truncate consistently on both hash + verify so any caller is safe regardless
# of multibyte content (schema char-limits don't bound byte length).
_BCRYPT_MAX_BYTES = 72


def _to_bcrypt_bytes(plain: str) -> bytes:
    return plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_to_bcrypt_bytes(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(plain), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(
    claims: dict[str, Any], expires_minutes: Optional[int] = None
) -> str:
    """Issue a signed JWT. `claims` should include `sub` (user id).
    `expires_minutes` overrides the default TTL (rememberMe, plan 10 D4)."""
    to_encode = dict(claims)
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes
        if expires_minutes is not None
        else settings.access_token_expire_minutes
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode/verify a JWT. Raises JWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
