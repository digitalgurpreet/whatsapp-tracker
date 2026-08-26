"""SQLAlchemy ORM models for persisted WhatsApp messages."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Message(Base):
    """A single inbound or outbound WhatsApp message captured from a Cloud API webhook.

    Duplicate deliveries from Meta are ignored via a unique constraint on `wamid`.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wamid: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    from_phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    to_phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    direction: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    timestamp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            "<Message id={id} wamid={wamid!r} direction={direction!r} "
            "from={from_phone!r}>"
        ).format(
            id=self.id,
            wamid=self.wamid,
            direction=self.direction,
            from_phone=self.from_phone,
        )
