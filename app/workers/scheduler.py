import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.orchestrator import run_follow_ups, run_orchestrator

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
scheduler.add_job(run_orchestrator, "interval", minutes=5, id="orchestrator", max_instances=1)
scheduler.add_job(run_follow_ups, "interval", minutes=15, id="follow_ups", max_instances=1)
