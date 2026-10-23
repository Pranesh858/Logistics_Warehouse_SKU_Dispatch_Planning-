import asyncio

import asyncio as _a
from typing import Literal

from fastapi import APIRouter, Depends, File, Response, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.core.audit import record
from app.core.auth import Admin, CurrentUser, ensure_warehouse, pick_warehouse, scope
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.modules.dispatch import service as dispatch_service
from app.modules.dispatch.models import LedgerEntry
from app.modules.forecast import dataset, orders, reports, service, supply
from app.modules.forecast.schemas import ForecastRequest

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/skus")
async def skus(user: CurrentUser):
    rows = await asyncio.to_thread(service.list_skus)
    wh = scope(user)
    return [r for r in rows if r["warehouse_id"] == wh] if wh else rows


@router.post("/run")
async def run(body: ForecastRequest, user: CurrentUser):
    wh = scope(user)
    if wh:
        if body.warehouse_ids and set(body.warehouse_ids) != {wh}:
            ensure_warehouse(user, next(w for w in body.warehouse_ids if w != wh))
        body.warehouse_ids = [wh]
    return await asyncio.to_thread(service.run_forecast, body.days, body.product_ids, body.warehouse_ids)


@router.get("/explain")
async def explain(product_id: int, warehouse_id: str, user: CurrentUser, days: int = Query(7, ge=1, le=28)):
    ensure_warehouse(user, warehouse_id)
    try:
        return await asyncio.to_thread(service.explain_forecast, product_id, warehouse_id, days)
    except IndexError:
        raise HTTPException(404, "No history for that SKU at that warehouse")


@router.get("/accuracy")
async def accuracy(user: CurrentUser, warehouse_id: str | None = None):
    """Predicted vs actual demand on past data: KPIs, daily series, error by forecast day, by warehouse and by SKU.
    A planner gets their own warehouse only."""
    try:
        return await asyncio.to_thread(service.accuracy_report, pick_warehouse(user, warehouse_id))
    except FileNotFoundError:
        raise HTTPException(404, "No accuracy report has been generated yet")


# ---- dataset upload and retraining (admin) -------------------------------------------------------------------------
MAX_UPLOAD_BYTES = 80 * 1024 * 1024


@router.post("/dataset/check")
async def dataset_check(admin: Admin, file: UploadFile = File(...)):
    """Read an uploaded CSV/Excel file and say what it contains. The live model is not touched."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is larger than 80 MB")
    return await asyncio.to_thread(dataset.stage, file.filename or "upload.csv", content)


@router.post("/dataset/apply")
async def dataset_apply(admin: Admin, force: bool = False):
    """Retrain on the old history plus the checked upload, in the background. Poll /forecast/dataset/status."""
    loop = asyncio.get_running_loop()

    async def rebuild_plan():
        async with AsyncSessionLocal() as db:
            await dispatch_service.recommend_plan(db, trigger="dataset_upload")

    def done(_result):  # called from the training thread
        orders.warm()
        _a.run_coroutine_threadsafe(rebuild_plan(), loop)

    return await asyncio.to_thread(dataset.start, force, done)


@router.post("/dataset/retrain")
async def dataset_retrain(admin: Admin):
    """Retrain on the sales history as it now stands, without uploading anything."""
    loop = asyncio.get_running_loop()

    async def rebuild_plan():
        async with AsyncSessionLocal() as db:
            await dispatch_service.recommend_plan(db, trigger="retrained")

    def done(_result):
        orders.warm()
        _a.run_coroutine_threadsafe(rebuild_plan(), loop)

    return await asyncio.to_thread(dataset.start_retrain, done, "manual")


@router.get("/dataset/status")
async def dataset_status(admin: Admin):
    return dataset.status()


@router.delete("/dataset/check")
async def dataset_discard(admin: Admin):
    return await asyncio.to_thread(dataset.discard)


# ---- units to order and downloadable reports --------------------------------------------------------------------------
async def _reserved(db: AsyncSession) -> dict:
    """Stock already promised to approved orders, per SKU x warehouse."""
    q = (select(LedgerEntry.product_id, LedgerEntry.warehouse_id, func.sum(LedgerEntry.qty_committed))
         .where(LedgerEntry.fulfilment == "RESERVED")
         .group_by(LedgerEntry.product_id, LedgerEntry.warehouse_id))
    return {(p, w): float(q_) for p, w, q_ in (await db.execute(q)).all()}


async def _needs(user, db, days, safety, warehouse_id, include_all=False):
    wh = pick_warehouse(user, warehouse_id)
    reserved = await _reserved(db)
    leads = await supply.lead_times(db)
    coming = await supply.on_order(db)
    return await asyncio.to_thread(orders.compute, days, safety, wh, reserved, include_all, leads,
                                   settings.default_lead_time_days, coming)


@router.get("/orders")
async def units_to_order(user: CurrentUser, db: AsyncSession = Depends(get_db), days: int = Query(7), safety: bool = True,
                         warehouse_id: str | None = None, include_covered: bool = False):
    """How many units to order per SKU and warehouse for the next 7, 14 or 28 days. Most urgent first.
    `include_covered` also returns the SKUs that need nothing, for looking one up."""
    return await _needs(user, db, days, safety, warehouse_id, include_covered)


MEDIA = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@router.get("/reports/{kind}")
async def report(kind: Literal["forecast", "orders", "accuracy"], user: CurrentUser, db: AsyncSession = Depends(get_db),
                 format: Literal["pdf", "xlsx"] = "pdf", days: int = Query(7), safety: bool = True, warehouse_id: str | None = None):
    """Download a report. PDF = the key points on a page or two; Excel = every row."""
    if kind == "accuracy":
        try:
            rep = await asyncio.to_thread(service.accuracy_report, pick_warehouse(user, warehouse_id))
        except FileNotFoundError:
            raise HTTPException(404, "No accuracy report has been generated yet")
        body = await asyncio.to_thread(reports.accuracy_pdf if format == "pdf" else reports.accuracy_xlsx, rep)
    else:
        res = await _needs(user, db, days, safety, warehouse_id, include_all=(kind == "forecast"))
        build = {("orders", "pdf"): reports.orders_pdf, ("orders", "xlsx"): reports.orders_xlsx,
                 ("forecast", "pdf"): reports.forecast_pdf, ("forecast", "xlsx"): reports.forecast_xlsx}[(kind, format)]
        body = await asyncio.to_thread(build, res)
    name = {"forecast": f"demand-forecast-{days}d", "orders": f"units-to-order-{days}d", "accuracy": "forecast-accuracy"}[kind]
    return Response(body, media_type=MEDIA[format], headers={"Content-Disposition": f'attachment; filename="{name}.{format}"'})


# ---- supplier lead times -----------------------------------------------------------------------------------------
class LeadTimeIn(BaseModel):
    product_id: int
    lead_time_days: int = Field(ge=0, le=supply.MAX_LEAD_DAYS)
    supplier: str = ""


@router.get("/lead-times")
async def read_lead_times(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """How long each SKU takes to arrive. Anything not listed uses the default."""
    return await supply.list_lead_times(db)


@router.put("/lead-times")
async def write_lead_time(body: LeadTimeIn, admin: Admin, db: AsyncSession = Depends(get_db)):
    out = await supply.set_lead_time(db, body.product_id, body.lead_time_days, body.supplier, admin.username)
    await record(db, admin, "lead_time_changed", f"SKU {body.product_id}: {body.lead_time_days} days")
    return out


@router.delete("/lead-times/{product_id}")
async def drop_lead_time(product_id: int, admin: Admin, db: AsyncSession = Depends(get_db)):
    await supply.clear_lead_time(db, product_id)
    await record(db, admin, "lead_time_changed", f"SKU {product_id}: back to the default")
    return {"product_id": product_id, "lead_time_days": settings.default_lead_time_days, "supplier": ""}
