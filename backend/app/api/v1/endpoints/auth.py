"""Authentication endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.deps import RequireAdmin, get_current_user
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.schemas.auth import (
    MeResponse,
    TokenResponse,
    UserLogin,
    UserPageResponse,
    UserRegister,
    UserResponse,
    UserUpdate,
)
from app.services.auth.service import AuthService

router = APIRouter()
_auth_service = AuthService()


@router.post(
    "/register",
    response_model=UserResponse,
    summary="用户注册",
    description="创建用户，用户名唯一，密码 bcrypt 哈希。",
)
async def register(
    body: UserRegister,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> User:
    existing = await session.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")
    user = User(
        username=body.username,
        hashed_password=get_password_hash(body.password),
        role="normal",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="用户登录",
    description="校验凭证并返回 JWT access_token。",
)
async def login(
    body: UserLogin,
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> TokenResponse:
    result = await session.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token({"sub": user.username})
    return TokenResponse(access_token=token)


@router.get(
    "/me",
    response_model=MeResponse,
    summary="当前用户",
    description="返回角色与状态，供前端 RBAC 菜单裁剪。",
)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


@router.get(
    "/users",
    response_model=UserPageResponse,
    summary="用户列表",
    description="admin 查看平台用户，用于禁用/启用账号。",
)
async def list_users(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> UserPageResponse:
    return await _auth_service.list_users(session, skip=skip, limit=limit)


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="更新用户",
    description="admin 禁用/启用用户（A-05）。",
)
async def update_user(
    user_id: int,
    body: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
) -> UserResponse:
    result = await _auth_service.update_user(session, user_id, body, current_user)
    await session.commit()
    return result
