from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.lead import Lead
from app.models.message import Message

router = APIRouter(prefix="")

# Load the template once at startup; fall back to a minimal stub if missing.
_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "chat_viewer_template.html"
try:
    _HTML_TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    _HTML_TEMPLATE = (
        "<!DOCTYPE html><html><body style='background:#000;color:#fff;"
        "font-family:sans-serif;padding:20px;'>"
        "<p>Template not found.</p></body></html>"
    )


@router.get("/chat-viewer", response_class=HTMLResponse)
async def chat_viewer():
    return HTMLResponse(content=_HTML_TEMPLATE)


@router.get("/api/chat/{chat_id}/messages")
async def get_chat_messages(chat_id: str, db: AsyncSession = Depends(get_db)):
    # Find the lead by linq_chat_id
    result = await db.execute(select(Lead).where(Lead.linq_chat_id == chat_id))
    lead = result.scalar_one_or_none()

    if lead is None:
        return JSONResponse(status_code=404, content={"error": "Chat not found"})

    # Fetch all messages for this lead ordered by sent_at ascending
    msg_result = await db.execute(
        select(Message)
        .where(Message.lead_id == lead.id)
        .order_by(Message.sent_at.asc())
    )
    messages = msg_result.scalars().all()

    # Determine latest_intent: most recent message with a non-null intent
    latest_intent = None
    for msg in reversed(messages):
        if msg.intent is not None:
            latest_intent = msg.intent
            break

    return {
        "lead": {
            "name": lead.name,
            "state": lead.state,
            "latest_intent": latest_intent,
        },
        "messages": [
            {
                "id": msg.id,
                "direction": msg.direction,
                "channel": msg.channel,
                "body": msg.body,
                "intent": msg.intent,
                "sent_at": msg.sent_at.isoformat(),
            }
            for msg in messages
        ],
    }
