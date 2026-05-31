import re
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from payments_processor.database.pure_base import PureBase


class Base(PureBase):
    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=None,
        onupdate=func.now(),
        nullable=True,
    )

    @declared_attr.directive
    def __tablename__(self) -> str:
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", self.__name__).lower()
        if not name.endswith("s"):
            name += "s"
        return name
