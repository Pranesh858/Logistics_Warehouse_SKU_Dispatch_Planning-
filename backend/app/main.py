from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core import audit as _audit  # noqa: F401  (registers the audit table)
from app.core.startup_checks import check_production_settings
from app.core.database import engine, Base
from app.core.database import AsyncSessionLocal
from app.modules.dispatch import service as dispatch_service
from app.modules.dispatch.router import router as dispatch_router
from app.modules.forecast.router import router as forecast_router
from app.modules.auth.router import router as auth_router
from app.modules.users import service as users_service
from app.modules.users.router import router as users_router
from app.integrations import models as _integration_models  # noqa: F401  (registers the tables)
from app.modules.forecast import supply as _supply_models  # noqa: F401  (registers supplier_lead_times)
from app.integrations import config_store as integration_config
from app.integrations import service as integration_service
from app.integrations.router import router as integrations_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_production_settings()
    if settings.auto_create_tables:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        await users_service.seed_users(db)
    async with AsyncSessionLocal() as db:
        await integration_config.load(db)
        await integration_service.load_overlay(db)
    if settings.auto_plan_on_startup:
        # The first recommended plan is built automatically; sending anything to the WMS still needs approval.
        async with AsyncSessionLocal() as db:
            await dispatch_service.seed_orders(db)
            await dispatch_service.seed_default_trucks(db)
            if await dispatch_service.current_plan(db) is None:
                await dispatch_service.recommend_plan(db, trigger="startup")
    if settings.warm_forecast_on_startup:
        # The units-to-order page needs a 28-day forecast; compute it in the background so the first visit is quick.
        import threading
        from app.modules.forecast import orders
        threading.Thread(target=orders.warm, daemon=True).start()
    import asyncio
    sched = asyncio.create_task(integration_service.scheduler(AsyncSessionLocal))
    yield
    sched.cancel()


app = FastAPI(
    title="warehouse-dispatch-planning-allocation-backend",
    description="Backend for demand-based warehouse SKU dispatch planning and allocation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(forecast_router, prefix="/api/v1")
app.include_router(dispatch_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "warehouse-dispatch-planning-allocation-backend"}
