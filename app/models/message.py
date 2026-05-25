import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MessageDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class MessageChannel(str, enum.Enum):
    text = "text"
    email = "email"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection))
    channel: Mapped[MessageChannel] = mapped_column(Enum(MessageChannel))
    body: Mapped[str] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
