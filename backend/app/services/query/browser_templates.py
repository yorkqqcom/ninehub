"""Browser template CRUD."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.browser import BrowserTemplate
from app.schemas.query_browser import BrowserTemplateCreate, BrowserTemplateResponse


class BrowserTemplateService:
    async def list_templates(
        self, session: AsyncSession, user_id: int, include_system: bool = True
    ) -> list[BrowserTemplateResponse]:
        q = select(BrowserTemplate)
        if include_system:
            q = q.where(
                (BrowserTemplate.user_id == user_id) | (BrowserTemplate.is_system.is_(True))
            )
        else:
            q = q.where(BrowserTemplate.user_id == user_id)
        rows = (await session.execute(q.order_by(BrowserTemplate.id))).scalars().all()
        return [self._to_response(r) for r in rows]

    async def create(
        self, session: AsyncSession, user_id: int, body: BrowserTemplateCreate
    ) -> BrowserTemplateResponse:
        row = BrowserTemplate(
            user_id=user_id,
            name=body.name,
            description=body.description,
            scope="user",
            is_system=False,
            payload_json=body.payload,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return self._to_response(row)

    async def get(self, session: AsyncSession, template_id: int, user_id: int) -> BrowserTemplateResponse:
        row = await session.get(BrowserTemplate, template_id)
        if row is None:
            raise NotFoundError("模板不存在")
        if not row.is_system and row.user_id != user_id:
            raise ForbiddenError("无权访问该模板")
        return self._to_response(row)

    async def delete(self, session: AsyncSession, template_id: int, user_id: int, is_admin: bool) -> None:
        row = await session.get(BrowserTemplate, template_id)
        if row is None:
            raise NotFoundError("模板不存在")
        if row.is_system and not is_admin:
            raise ForbiddenError("系统模板不可删除")
        if not row.is_system and row.user_id != user_id:
            raise ForbiddenError("无权删除该模板")
        await session.delete(row)
        await session.commit()

    async def update(
        self,
        session: AsyncSession,
        template_id: int,
        user_id: int,
        *,
        name: str | None = None,
        payload: dict | None = None,
        description: str | None = None,
    ) -> BrowserTemplateResponse:
        row = await session.get(BrowserTemplate, template_id)
        if row is None:
            raise NotFoundError("模板不存在")
        if row.is_system:
            raise ForbiddenError("系统模板不可修改")
        if row.user_id != user_id:
            raise ForbiddenError("无权修改该模板")
        if name is not None:
            row.name = name
        if payload is not None:
            row.payload_json = payload
        if description is not None:
            row.description = description
        await session.commit()
        await session.refresh(row)
        return self._to_response(row)

    def _to_response(self, row: BrowserTemplate) -> BrowserTemplateResponse:
        return BrowserTemplateResponse(
            id=row.id,
            name=row.name,
            description=row.description,
            scope=row.scope,
            is_system=row.is_system,
            payload=row.payload_json or {},
            user_id=row.user_id,
        )
