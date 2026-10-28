"""Moving our picture of physical stock.

Stock reaches us from three places: the sales history (the starting figure), a WMS feed when one is
connected, and our own actions. The last of those is what this module writes. When goods ship out, leave on a
transfer or arrive on one, the shelf figure has genuinely changed, and the plan must see it immediately -
otherwise the same units get promised twice. Where a WMS feed is connected, its next report overwrites
whatever we wrote here with the authoritative figure.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.models import StockLevel
from app.modules.forecast.runtime import runtime


async def apply_delta(db: AsyncSession, deltas: dict[tuple[int, str], float], source: str) -> None:
    """Shift stock per (product_id, warehouse_id). Negative takes units off the shelf, positive puts them on.

    Stock never goes below zero: a negative result means our figure was already behind what really happened,
    and an impossible number would be worse than a stale one.
    """
    if not deltas:
        return
    import asyncio
    snap = await asyncio.to_thread(runtime.stock_snapshot)
    current = {(int(r.product_id), r.warehouse_id): float(r.stock_on_hand) for r in snap.itertuples()}
    existing = {(r.product_id, r.warehouse_id): r for r in (await db.execute(select(StockLevel))).scalars().all()}
    live = dict(runtime._live_stock)
    for key, delta in deltas.items():
        if not delta:
            continue
        qty = max(0.0, current.get(key, 0.0) + float(delta))
        row = existing.get(key)
        if row is None:
            db.add(StockLevel(product_id=key[0], warehouse_id=key[1], qty=qty, source=source,
                              updated_at=datetime.now()))
        else:
            row.qty, row.source, row.updated_at = qty, source, datetime.now()
        live[key] = qty
    await db.commit()
    runtime.set_live_stock(live)
