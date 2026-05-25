from fastapi import APIRouter

from app.services.orchestrator import run_follow_ups, run_orchestrator

router = APIRouter(prefix="/admin")


@router.post("/trigger/orchestrator")
async def trigger_orchestrator():
    """Manually trigger the orchestrator — useful for testing."""
    await run_orchestrator()
    return {"ok": True, "ran": "orchestrator"}


@router.post("/trigger/follow-ups")
async def trigger_follow_ups():
    await run_follow_ups()
    return {"ok": True, "ran": "follow_ups"}
