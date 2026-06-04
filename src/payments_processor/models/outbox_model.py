from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Enum, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from payments_processor.constants import PaymentsConstants
from payments_processor.database import Base
from payments_processor.enums import OutboxStatusEnum
from payments_processor.utils import uuid7


class Outbox(Base):
    __tablename__ = "outbox"  # pyright: ignore[reportAssignmentType]

    IX_OUTBOX_PENDING = "ix_outbox_pending"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )
    aggregate_type: Mapped[str] = mapped_column(
        String(PaymentsConstants.OUTBOX_AGGREGATE_TYPE_MAX_LEN),
        nullable=False,
    )
    aggregate_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(PaymentsConstants.OUTBOX_EVENT_TYPE_MAX_LEN),
        nullable=False,
    )
    routing_key: Mapped[str] = mapped_column(
        String(PaymentsConstants.OUTBOX_ROUTING_KEY_MAX_LEN),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    status: Mapped[OutboxStatusEnum] = mapped_column(
        Enum(OutboxStatusEnum, native_enum=False),
        nullable=False,
        default=OutboxStatusEnum.PENDING,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    __table_args__ = (
        Index(
            IX_OUTBOX_PENDING,
            "next_attempt_at",
            "created_at",
            postgresql_where=(status == OutboxStatusEnum.PENDING),
        ),
    )
