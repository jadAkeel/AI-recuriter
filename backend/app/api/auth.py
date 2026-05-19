from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.deps import get_current_user, require_any_role
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UpdateRoleRequest,
    UserResponse,
)
from app.services.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_user_by_id,
    list_users,
    register_user,
    update_user_role,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, session: AsyncSession = Depends(get_db_session)) -> UserResponse:
    """
    Registers a new user account.
    """
    try:
        user = await register_user(session, request.email, request.password, request.full_name)
        return UserResponse(id=user.id, email=user.email, full_name=user.full_name, role=user.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest, session: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    """
    Authenticates a user and returns access and refresh tokens.
    """
    user = await authenticate_user(session, request.email, request.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest, session: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    """
    Issues fresh tokens from a valid refresh token.
    """
    payload = decode_token(request.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = await get_user_by_id(session, payload["sub"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/auth/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    """
    Returns the currently authenticated user.
    """
    return UserResponse(id=user.id, email=user.email, full_name=user.full_name, role=user.role)


@router.get("/auth/users", response_model=list[UserResponse])
async def users_list(
    _: User = Depends(require_any_role("owner", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> list[UserResponse]:
    """
    Lists users for administrators.
    """
    users = await list_users(session)
    return [UserResponse(id=u.id, email=u.email, full_name=u.full_name, role=u.role) for u in users]


@router.patch("/auth/users/{user_id}/role", response_model=UserResponse)
async def change_user_role(
    user_id: str,
    request: UpdateRoleRequest,
    current_user: User = Depends(require_any_role("owner", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """
    Updates a user role with owner-role protections.
    """
    if request.role.lower() == "owner" and current_user.role.lower() != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner can assign owner role")

    try:
        updated = await update_user_role(session, user_id, request.role)
        return UserResponse(id=updated.id, email=updated.email, full_name=updated.full_name, role=updated.role)
    except ValueError as exc:
        message = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if message == "User not found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=message) from exc
