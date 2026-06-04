from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.database import Base


class BaseRepository[ModelType: Base]:
    model: type[ModelType]

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, obj_id: UUID) -> ModelType | None:
        return await self.session.get(self.model, obj_id)

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters: str | bool | float | datetime | None,
    ) -> tuple[list[ModelType], int]:
        statement = select(self.model).filter_by(**filters).offset(skip).limit(limit).order_by(self.model.created_at)
        count_statement = select(func.count()).select_from(self.model).filter_by(**filters)

        result = await self.session.execute(statement)
        count_result = await self.session.execute(count_statement)

        items = list(result.scalars().all())
        total = count_result.scalar() or 0

        return items, total

    def add(self, db_obj: ModelType) -> None:
        self.session.add(db_obj)

    async def delete_by_id(self, obj_id: UUID) -> UUID | None:
        id_column: Any = self.model.__table__.c["id"]
        statement = delete(self.model).where(id_column == obj_id).returning(id_column)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()
