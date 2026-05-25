from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class InboundMessage:
    sender: str        # E.164 phone or email address
    body: str
    channel: str       # "text" or "email"
    raw: dict          # original webhook payload
    chat_id: str | None = None  # Linq chat UUID for threading


class ChannelAdapter(ABC):
    @abstractmethod
    async def send(self, to: str, body: str) -> dict:
        """Send a message. Returns provider response."""

    @abstractmethod
    def parse_inbound(self, payload: dict) -> InboundMessage | None:
        """Parse a webhook payload. Returns None if not an inbound message event."""
