"""Authentication business logic."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.user import User
from app.schemas.auth import UserPageResponse, UserResponse, UserUpdate


class AuthService:
    async def list_users(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
    ) -> UserPageResponse:
        total = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        result = await session.execute(
            select(User).order_by(User.id.asc()).offset(skip).limit(limit)
        )
        page = (skip // limit) + 1 if limit else 1
        return UserPageResponse(
            items=[UserResponse.model_validate(u) for u in result.scalars().all()],
            total=total,
            page=page,
            size=limit,
        )

    async def update_user(
        self,
        session: AsyncSession,
        user_id: int,
        body: UserUpdate,
        current_user: User,
    ) -> UserResponse:
        user = await session.get(User, user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        if user.id == current_user.id and body.is_active is False:
            raise ValidationError("不能禁用当前登录账号")
        if body.is_active is not None:
            user.is_active = body.is_active
        await session.flush()
        await session.refresh(user)
        return UserResponse.model_validate(user)
