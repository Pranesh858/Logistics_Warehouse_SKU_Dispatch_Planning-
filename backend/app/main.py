import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from app.modules.alerts import models as _alert_models  # noqa: F401  (registers the alerts table)
from app.modules.alerts.router import router as alerts_router
from app.modules.stock import models as _stock_models  # noqa: F401  (registers the master data and stock ledger)
from app.modules.stock import service as stock_service
from app.modules.stock.router import router as stock_router
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
        await stock_service.seed(db)          # master data and opening stock, the first time only
        await stock_service.load_cache(db)
    async with AsyncSessionLocal() as db:
        await users_service.seed_users(db)    # one planner per warehouse, so it needs the warehouses loaded
    async with AsyncSessionLocal() as db:
        await integration_config.load(db)
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
    # Alerts are only worth having if they appear without anyone asking, so the rules are swept on a timer
    # of their own rather than when somebody opens the page.
    from app.modules.alerts import scheduler as alert_scheduler
    alerts_task = asyncio.create_task(alert_scheduler.run(AsyncSessionLocal))
    yield
    sched.cancel()
    alerts_task.cancel()


app = FastAPI(
    title="warehouse-dispatch-planning-allocation-backend",
    description="Backend for demand-based warehouse SKU dispatch planning and allocation",
    version="0.1.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def unexpected_errors(request: Request, call_next):
    """A crash still answers with a JSON error the dashboard can read.

    Left alone, an unhandled exception is turned into a 500 by the outermost layer, outside CORS, so the reply has
    no CORS headers: the browser hides it and the dashboard can only say it cannot reach the backend. Registered
    before CORS so that CORS wraps it and its reply carries the headers."""
    try:
        return await call_next(request)
    except Exception:
        logging.getLogger("uvicorn.error").exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={
            "detail": "Something went wrong on the server and the request was not completed. "
                      "The error is in the backend log."})


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
app.include_router(stock_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "warehouse-dispatch-planning-allocation-backend"}
