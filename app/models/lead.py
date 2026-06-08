import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LeadTemperature(str, enum.Enum):
    hot_inbound = "hot_inbound"
    aged = "aged"


class LeadState(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    engaged = "engaged"
    qualifying = "qualifying"
    booked = "booked"
    handed_off = "handed_off"
    no_reply = "no_reply"
    dormant = "dormant"


class LeadChannel(str, enum.Enum):
    text = "text"
    email = "email"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    property_interest: Mapped[str | None] = mapped_column(String(500), nullable=True)
    temperature: Mapped[LeadTemperature] = mapped_column(
        Enum(LeadTemperature), default=LeadTemperature.aged
    )
    state: Mapped[LeadState] = mapped_column(
        Enum(LeadState), default=LeadState.new, index=True
    )
    channel: Mapped[LeadChannel] = mapped_column(
        Enum(LeadChannel), default=LeadChannel.email
    )
    consent_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    linq_chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    calcom_booking_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    twenty_person_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    twenty_opportunity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latest_intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    reply_first_pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
