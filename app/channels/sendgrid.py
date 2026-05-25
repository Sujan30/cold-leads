import logging

import httpx

from app.channels.base import ChannelAdapter, InboundMessage
from app.config import settings

logger = logging.getLogger(__name__)

SENDGRID_API_BASE = "https://api.sendgrid.com/v3"


class SendGridAdapter(ChannelAdapter):
    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=SENDGRID_API_BASE,
            headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
            timeout=10.0,
        )

    async def send(self, to: str, body: str, subject: str = "Following up") -> dict:
        if not settings.sendgrid_api_key:
            logger.warning("SendGrid not configured — skipping email to %s", to)
            return {}
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": settings.sendgrid_from_email or "noreply@example.com"},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }
        response = await self._client.post("/mail/send", json=payload)
        response.raise_for_status()
        logger.info("SendGrid sent to %s", to)
        return {"status": "sent"}

    def parse_inbound(self, payload: dict) -> InboundMessage | None:
        # SendGrid inbound parse sends form data; envelope + text fields
        sender = payload.get("from", "")
        body = payload.get("text") or payload.get("html", "")
        if not sender or not body:
            return None
        return InboundMessage(
            sender=sender,
            body=body.strip(),
            channel="email",
            raw=payload,
        )

    async def aclose(self):
        await self._client.aclose()


sendgrid = SendGridAdapter()
