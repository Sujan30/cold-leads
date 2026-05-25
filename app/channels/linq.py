import hmac
import hashlib
import base64
import logging

import httpx

from app.channels.base import ChannelAdapter, InboundMessage
from app.config import settings

logger = logging.getLogger(__name__)

LINQ_API_BASE = "https://api.linqapp.com/api/partner/v3"

_BLOCKED_PATTERNS = ("http://", "https://", ".com", ".io", ".net", "cal.com")


def lint_first_text(body: str) -> None:
    """Raise if the body contains links or domain refs — Linq compliance rule."""
    lower = body.lower()
    for pattern in _BLOCKED_PATTERNS:
        if pattern in lower:
            raise ValueError(
                f"First text must not contain links (found '{pattern}'). "
                "Share booking links only after the lead has engaged."
            )


def _build_message(text: str) -> dict:
    return {"parts": [{"type": "text", "value": text}]}


class LinqAdapter(ChannelAdapter):
    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=LINQ_API_BASE,
            headers={"Authorization": f"Bearer {settings.linq_api_token}"},
            timeout=10.0,
        )

    async def send(self, to: str, body: str) -> dict:
        """Send to an existing chat or create a new one."""
        # First create a chat (Linq's send-to-new-number flow)
        payload = {
            "to": [to],
            "from": settings.linq_phone_number,
            "message": _build_message(body),
        }
        response = await self._client.post("/chats", json=payload)
        response.raise_for_status()
        data = response.json()
        logger.info("Linq /chats 201 response: %s", data)
        chat_id = (
            data.get("chat_id")
            or (data.get("chat") or {}).get("id")
            or data.get("id")
        )
        message_id = (data.get("message") or {}).get("id")
        logger.info("Linq sent to %s — chat_id: %s msg_id: %s", to, chat_id, message_id)
        data["_chat_id"] = chat_id
        return data

    async def send_to_chat(self, chat_id: str, body: str) -> dict:
        """Send a message in an existing chat thread."""
        response = await self._client.post(
            f"/chats/{chat_id}/messages",
            json={"message": _build_message(body)},
        )
        response.raise_for_status()
        return response.json()

    async def send_first_touch(self, to: str, body: str) -> dict:
        """Send a first-touch text — enforces no-link compliance rule."""
        lint_first_text(body)
        return await self.send(to, body)

    def verify_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        if not settings.linq_webhook_signing_secret:
            return True
        secret = settings.linq_webhook_signing_secret.encode()
        expected = base64.b64encode(
            hmac.new(secret, payload_bytes, hashlib.sha256).digest()
        ).decode()
        return hmac.compare_digest(expected, signature_header)

    def parse_inbound(self, payload: dict) -> InboundMessage | None:
        event_type = payload.get("event_type", "")
        data = payload.get("data", {})
        direction = data.get("direction", "")

        # Only process inbound messages from the lead
        if event_type not in ("message.received",) and direction != "inbound":
            return None
        if direction == "outbound":
            return None

        sender = (data.get("sender_handle") or {}).get("handle", "")
        chat_id = (data.get("chat") or {}).get("id")

        parts = data.get("parts") or []
        body = ""
        for part in parts:
            if part.get("type") == "text":
                body = part.get("value", "")
                break

        if not sender or not body:
            return None

        return InboundMessage(
            sender=sender,
            body=body,
            channel="text",
            raw=payload,
            chat_id=chat_id,
        )

    async def ensure_contact(self, phone: str, name: str = "") -> bool:
        """Register a phone number as a contact on the Linq account.
        Returns True if successful, False if the endpoint isn't supported."""
        try:
            payload = {"phone_number": phone}
            if name:
                payload["name"] = name
            response = await self._client.post("/contacts", json=payload)
            if response.status_code in (200, 201, 409):  # 409 = already exists
                logger.info("Linq contact ensured for %s (status %s)", phone, response.status_code)
                return True
            logger.warning("Linq ensure_contact returned %s for %s — may not be supported",
                           response.status_code, phone)
            return False
        except Exception as e:
            logger.warning("Linq ensure_contact failed for %s: %s", phone, e)
            return False

    async def aclose(self):
        await self._client.aclose()


linq = LinqAdapter()
