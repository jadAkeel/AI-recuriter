from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.models.candidate import Candidate
from app.models.user import User
from app.services.auth import decode_token, get_user_by_id
from sqlalchemy import select

security = HTTPBearer(auto_error=False)
STAFF_ROLES = {"owner", "admin", "recruiter"}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub") if payload else None
    if payload is None or payload.get("type") != "access" or not isinstance(user_id, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def require_role(role: str):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user
    return _check


def require_any_role(*roles: str):
    allowed = {role.lower() for role in roles}

    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role.lower() not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _check


async def ensure_candidate_access(session: AsyncSession, user: User, candidate_id: str) -> None:
    """Allow staff users to access any candidate and candidates to access only their own CV row.

    The current schema does not link users to candidates directly, so ownership is derived from
    the authenticated user's email matching the candidate email.
    """

    role = user.role.lower()
    if role in STAFF_ROLES:
        return
    if role != "candidate":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    result = await session.execute(select(Candidate.id).where(Candidate.email == user.email))
    allowed_ids = set(result.scalars().all())
    if candidate_id not in allowed_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
