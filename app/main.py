import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request

from app.config import settings
from app.routers import health, webhooks
from app.routers.admin import router as admin_router
from app.routers.chat_viewer import router as chat_viewer_router
from app.routers.leads import router as leads_router
from app.workers.scheduler import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    if settings.agents_phone:
        from app.channels.linq import linq
        await linq.ensure_contact(settings.agents_phone, settings.agents_name)
    if settings.mode == "dev":
        await _seed_dev_lead()
    from app.services.orchestrator import run_orchestrator
    from app.services.sweeper import run_sweeper
    asyncio.create_task(run_orchestrator())
    asyncio.create_task(run_sweeper())
    yield
    scheduler.shutdown()


async def _seed_dev_lead():
    from scripts.seed_test_leads import seed
    await seed()
    logger.info("[DEV] Dev leads seeded via seed_test_leads")


app = FastAPI(title="Cold Leads Agent", lifespan=lifespan)

app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(admin_router)
app.include_router(leads_router)
app.include_router(chat_viewer_router)


# Linq posts webhooks to the bare ngrok URL (no path) — catch them here.
@app.post("/")
async def root_linq_webhook(request: Request, background_tasks: BackgroundTasks):
    logger.info("[ROOT WEBHOOK] POST / received — forwarding to Linq handler")
    return await webhooks._process_linq_request(request, background_tasks)
