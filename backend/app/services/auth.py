from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User

ALGORITHM = "HS256"
VALID_ROLES = {"candidate", "recruiter", "admin", "owner"}


def normalize_email(email: str) -> str:
    """
    Normalizes an email address before lookup or storage.
    """
    return email.strip().lower()


def hash_password(password: str) -> str:
    """
    Hashes a password for safe storage.
    """
    # Truncate password to 72 bytes (bcrypt algorithm limit) to prevent errors
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    """
    Checks a plain password against a stored password hash.
    """
    try:
        plain_bytes = plain.encode('utf-8')[:72]
        hashed_bytes = hashed.encode('utf-8')
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception:
        return False


def create_access_token(user_id: str, role: str) -> str:
    """
    Creates a signed JWT access token for a user.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """
    Creates a signed JWT refresh token for a user.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=settings.refresh_token_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """
    Decodes and validates a JWT token payload.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
        return payload if isinstance(payload, dict) else None
    except JWTError:
        return None


async def register_user(session: AsyncSession, email: str, password: str, full_name: str) -> User:
    """
    Creates a new user account with a hashed password.
    """
    email = normalize_email(email)
    full_name = " ".join(full_name.strip().split())
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise ValueError("Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role="candidate",
    )
    session.add(user)
    await session.commit()
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    """
    Authenticates a user by email and password.
    """
    stmt = select(User).where(User.email == normalize_email(email))
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


async def get_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    """
    Loads a user by database ID.
    """
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """
    Loads a user by normalized email address.
    """
    stmt = select(User).where(User.email == normalize_email(email))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_users(session: AsyncSession) -> list[User]:
    """
    Lists all users ordered by email.
    """
    stmt = select(User).order_by(User.email.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_user_role(session: AsyncSession, user_id: str, role: str) -> User:
    """
    Updates a user role after validating allowed roles.
    """
    normalized_role = role.lower().strip()
    if normalized_role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role}")

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise ValueError("User not found")

    user.role = normalized_role
    await session.commit()
    await session.refresh(user)
    return user
