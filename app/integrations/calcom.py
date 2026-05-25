import logging
import zoneinfo
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

CAL_API_BASE = "https://api.cal.com/v2"
CAL_API_VERSION = "2024-08-13"

_PT = zoneinfo.ZoneInfo("America/Los_Angeles")
_MIN_HOUR_PT = 9   # don't suggest slots before 9 AM Pacific


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.cal_api_key}",
        "cal-api-version": CAL_API_VERSION,
        "Content-Type": "application/json",
    }


def booking_link() -> str:
    return f"https://cal.com/{settings.cal_username}/{settings.cal_event_slug}"


async def get_available_slots(start: datetime, end: datetime) -> list[datetime]:
    """Return available slot datetimes between start and end."""
    params = {
        "eventTypeId": settings.cal_event_type_id,
        "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{CAL_API_BASE}/slots/available", headers=_headers(), params=params)
    if resp.status_code != 200:
        logger.error("[CALCOM] get_available_slots failed %d: %s", resp.status_code, resp.text[:300])
        return []
    data = resp.json().get("data", {})
    slots: list[datetime] = []
    for day_slots in data.get("slots", {}).values():
        for slot in day_slots:
            t = slot.get("time", "")
            if t:
                slots.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
    return sorted(slots)


async def is_slot_available(proposed: datetime) -> bool:
    """Check if a specific slot is available by querying the full day."""
    day_start = proposed.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = proposed.replace(hour=23, minute=59, second=59, microsecond=0)
    slots = await get_available_slots(day_start, day_end)
    return any(abs((s - proposed).total_seconds()) < 60 for s in slots)


async def get_next_slots(n: int = 3) -> list[datetime]:
    """Return the next n available slots starting from now, skipping early-morning hours."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7)
    slots = await get_available_slots(now, end)
    slots = [s for s in slots if s.astimezone(_PT).hour >= _MIN_HOUR_PT]
    return slots[:n]


async def create_booking(lead_name: str, lead_email: str, start: datetime, notes: str = "") -> str | None:
    """
    Create a Cal.com booking. Returns the booking UID or None on failure.
    Booking creation is unauthenticated per Cal.com docs.
    """
    payload = {
        "eventTypeId": settings.cal_event_type_id,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attendee": {
            "name": lead_name,
            "email": lead_email,
            "timeZone": "America/Los_Angeles",
        },
    }
    if notes:
        payload["bookingFieldsResponses"] = {"notes": notes}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{CAL_API_BASE}/bookings",
            headers={"cal-api-version": "2026-02-25", "Content-Type": "application/json"},
            json=payload,
        )
    if resp.status_code not in (200, 201):
        logger.error("[CALCOM] create_booking failed %d: %s", resp.status_code, resp.text[:300])
        return None
    uid = resp.json().get("data", {}).get("uid")
    logger.info("[CALCOM] Booking created uid=%s for %s", uid, lead_email)
    return uid
