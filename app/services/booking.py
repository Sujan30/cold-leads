import logging
import zoneinfo
from datetime import datetime, timezone

from app.ai.client import complete

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """\
Extract the meeting date and time from this message. \
Today is {today}. The lead is in America/Los_Angeles ({tz_context}). \
Interpret all times as Pacific and output ONLY an ISO 8601 UTC datetime string \
(e.g. "2026-05-28T22:00:00Z") or the word "null" if no specific date/time is mentioned. \
No explanation. No other text. Just the string.
Message: {message}"""


async def extract_proposed_time(message: str) -> datetime | None:
    """Use Claude Haiku to parse a natural language time from a lead message."""
    pt = zoneinfo.ZoneInfo("America/Los_Angeles")
    now_local = datetime.now(pt)
    today_str = now_local.strftime("%A, %B %-d, %Y")
    offset = now_local.strftime("UTC%z")  # e.g. "UTC-0700"
    prompt = _EXTRACT_PROMPT.format(today=today_str, tz_context=offset, message=message)
    raw = (await complete(prompt, model="claude-haiku-4-5-20251001", max_tokens=32)).strip('"').splitlines()[0].strip()
    logger.info("[BOOKING] extract_proposed_time raw=%r", raw)
    if raw.lower() == "null" or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except ValueError:
        logger.warning("[BOOKING] Could not parse extracted time: %r", raw)
        return None


def format_slot(dt: datetime) -> str:
    """Human-readable slot string in Pacific time."""
    pt = zoneinfo.ZoneInfo("America/Los_Angeles")
    return dt.astimezone(pt).strftime("%A, %B %-d at %-I:%M %p %Z")
