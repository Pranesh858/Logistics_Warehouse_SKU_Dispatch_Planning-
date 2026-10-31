"""The one way stock changes.

Every writer (WMS sync and webhooks, manual counts, shipments, transfers, purchase order receipts) goes through
`apply` or `count`. Each updates the stock figure and writes a movement in the same transaction, then refreshes
the in-memory copy the planning code reads. Nothing else should write `stock_levels`.

Stock never goes below zero: a movement that would take it there takes it to zero, and the movement records what
really came off the shelf. A negative figure would mean our picture was already behind reality, and an impossible
number is worse than a stale one.
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import locks
from app.core.config import settings
from app.integrations.models import StockLevel
from app.modules.forecast.runtime import runtime
from app.modules.stock.models import ADJUSTMENT, OPENING, Sku, StockMovement, Warehouse

Key = tuple[int, str]


@dataclass
class Move:
    product_id: int
    warehouse_id: str
    qty: float                  # signed: + onto the shelf, - off it
    kind: str
    ref: str | None = None


# ----------------------------------------------------------------- writing
async def apply(db: AsyncSession, moves: list[Move], *, source: str, username: str | None = None,
                reason: str | None = None) -> list[StockMovement]:
    """Apply signed movements and record each one. Returns the movements written (zero-unit ones are skipped)."""
    async with locks.named("stock"):
        return await _apply(db, moves, source=source, username=username, reason=reason)


async def _apply(db: AsyncSession, moves: list[Move], *, source: str, username: str | None,
                 reason: str | None) -> list[StockMovement]:
    moves = [m for m in moves if m.qty]
    if not moves:
        return []
    keys = {(int(m.product_id), m.warehouse_id) for m in moves}
    rows = {(r.product_id, r.warehouse_id): r for r in (await db.execute(select(StockLevel))).scalars()
            if (r.product_id, r.warehouse_id) in keys}
    now = datetime.now()
    written = []
    for m in moves:
        key = (int(m.product_id), m.warehouse_id)
        row = rows.get(key)
        if row is None:     # first stock of this SKU at this warehouse, e.g. a transfer to a new location
            row = rows[key] = StockLevel(product_id=key[0], warehouse_id=key[1], qty=0.0, source=source, updated_at=now)
            db.add(row)
        before = float(row.qty)
        after = max(0.0, before + float(m.qty))
        if after == before:
            continue
        row.qty, row.source, row.updated_at = after, source, now
        mv = StockMovement(product_id=key[0], warehouse_id=key[1], kind=m.kind, qty=round(after - before, 4),
                           qty_after=after, ref=m.ref, source=source, username=username,
                           reason=(reason or "").strip() or None, at=now)
        db.add(mv)
        written.append(mv)
    await db.commit()
    _refresh({k: float(r.qty) for k, r in rows.items()})
    return written


async def count(db: AsyncSession, counts: dict[Key, float], *, source: str, username: str | None = None,
                reason: str | None = None) -> int:
    """A count replaces what we thought was on the shelf; the difference is recorded as an ADJUSTMENT.
    Returns how many figures actually changed.

    The figure is read and changed under one lock: two identical counts arriving together must not each see the
    old figure and each add the difference."""
    async with locks.named("stock"):
        return await _count(db, counts, source=source, username=username, reason=reason)


async def _count(db: AsyncSession, counts: dict[Key, float], *, source: str, username: str | None,
                 reason: str | None) -> int:
    rows = {(r.product_id, r.warehouse_id): r for r in (await db.execute(select(StockLevel))).scalars()}
    moves, now = [], datetime.now()
    for (p, w), q in counts.items():
        row = rows.get((p, w))
        if row is not None and abs(float(q) - float(row.qty)) <= 1e-6:
            row.source, row.updated_at = source, now    # confirmed, not moved: who last vouched for the figure
            continue
        moves.append(Move(p, w, float(q) - (float(row.qty) if row is not None else 0.0), ADJUSTMENT))
    written = await _apply(db, moves, source=source, username=username, reason=reason)
    await db.commit()
    return len(written)


def _refresh(changed: dict[Key, float]) -> None:
    stock = dict(runtime._stock)
    stock.update(changed)
    runtime.set_stock(stock)


# ----------------------------------------------------------------- reading
async def load_cache(db: AsyncSession) -> int:
    """At startup (and in tests): copy the stock and master tables into memory for the planning code."""
    stock = {(r.product_id, r.warehouse_id): float(r.qty) for r in (await db.execute(select(StockLevel))).scalars()}
    skus = {s.product_id: {"product_name": s.product_name, "category": s.category}
            for s in (await db.execute(select(Sku))).scalars()}
    cities = {w.warehouse_id: w.city for w in (await db.execute(select(Warehouse))).scalars()}
    runtime.set_master(skus, cities)
    runtime.set_stock(stock)
    return len(stock)


def view(m: StockMovement) -> dict:
    return {"id": m.id, "product_id": m.product_id, "warehouse_id": m.warehouse_id, "kind": m.kind,
            "qty": m.qty, "qty_after": m.qty_after, "ref": m.ref, "source": m.source, "username": m.username,
            "reason": m.reason, "at": m.at.isoformat() if m.at else None}


async def movements(db: AsyncSession, product_id: int | None = None, warehouse_id: str | None = None,
                    kind: str | None = None, limit: int = 200) -> list[dict]:
    """Newest first."""
    q = select(StockMovement)
    if product_id is not None:
        q = q.where(StockMovement.product_id == product_id)
    if warehouse_id:
        q = q.where(StockMovement.warehouse_id == warehouse_id)
    if kind:
        q = q.where(StockMovement.kind == kind.upper())
    rows = (await db.execute(q.order_by(StockMovement.at.desc(), StockMovement.id.desc()).limit(limit))).scalars()
    return [view(m) for m in rows]


# ----------------------------------------------------------------- seeding
def _read(path: str) -> pd.DataFrame | None:
    return pd.read_csv(path) if Path(path).exists() else None


async def seed(db: AsyncSession) -> dict:
    """Fill the master and stock tables from the seed files, once. Safe to run on every start.

    Warehouses and SKUs are added when missing. A SKU x warehouse pair with no stock row gets its seed figure as
    OPENING stock. A stock row with no movement yet (a database from before the stock ledger existed) gets an
    OPENING movement for the figure it already holds, so its history starts somewhere.
    """
    out = {"warehouses": 0, "skus": 0, "opening": 0}
    if not settings.seed_stock_on_startup:
        return out
    have_wh = set((await db.execute(select(Warehouse.warehouse_id))).scalars())
    wh = _read(settings.seed_warehouses_path)
    for r in ([] if wh is None else wh.itertuples()):
        if r.warehouse_id not in have_wh:
            db.add(Warehouse(warehouse_id=r.warehouse_id, city=r.city))
            out["warehouses"] += 1
    have_sku = set((await db.execute(select(Sku.product_id))).scalars())
    sk = _read(settings.seed_skus_path)
    for r in ([] if sk is None else sk.itertuples()):
        if int(r.product_id) not in have_sku:
            db.add(Sku(product_id=int(r.product_id), product_name=r.product_name, category=r.category,
                       is_organic=str(r.is_organic).lower() in ("true", "1", "yes"),
                       shelf_life_days=None if pd.isna(r.shelf_life_days) else int(r.shelf_life_days),
                       weight_g=None if pd.isna(r.weight_g) else float(r.weight_g)))
            out["skus"] += 1

    rows = {(r.product_id, r.warehouse_id): r for r in (await db.execute(select(StockLevel))).scalars()}
    with_history = {(p, w) for p, w in (await db.execute(
        select(StockMovement.product_id, StockMovement.warehouse_id).distinct())).all()}
    now = datetime.now()
    st = _read(settings.seed_stock_path)
    for r in ([] if st is None else st.itertuples()):
        key = (int(r.product_id), r.warehouse_id)
        if key not in rows:
            qty = float(r.stock_on_hand)
            rows[key] = StockLevel(product_id=key[0], warehouse_id=key[1], qty=qty, source="seed", updated_at=now)
            db.add(rows[key])
    for key, row in rows.items():
        if key not in with_history:
            db.add(StockMovement(product_id=key[0], warehouse_id=key[1], kind=OPENING, qty=float(row.qty),
                                 qty_after=float(row.qty), source="seed", reason="Opening stock", at=now))
            out["opening"] += 1
    await db.commit()
    return out


async def register_from_history(db: AsyncSession) -> int:
    """After a dataset upload or retrain: SKU x warehouse pairs the sales history knows and the stock table does not
    get master data and their latest stock from the history, as OPENING stock. Existing pairs are left alone - the
    history is sales, not a stock count. Returns how many pairs were added."""
    import asyncio

    frame = await asyncio.to_thread(lambda: runtime.frame)
    have = {(r.product_id, r.warehouse_id) for r in (await db.execute(select(StockLevel))).scalars()}
    latest = frame.sort_values("date").groupby(["product_id", "warehouse_id"], as_index=False, observed=True).tail(1)
    new = [r for r in latest.itertuples() if (int(r.product_id), str(r.warehouse_id)) not in have]
    if not new:
        return 0
    have_wh = set((await db.execute(select(Warehouse.warehouse_id))).scalars())
    have_sku = set((await db.execute(select(Sku.product_id))).scalars())
    for r in new:
        pid, wh = int(r.product_id), str(r.warehouse_id)
        if wh not in have_wh:
            db.add(Warehouse(warehouse_id=wh, city=str(r.city)))
            have_wh.add(wh)
        if pid not in have_sku:
            db.add(Sku(product_id=pid, product_name=str(r.product_name), category=str(r.category),
                       is_organic=bool(getattr(r, "is_organic", False)),
                       shelf_life_days=None if pd.isna(r.shelf_life_days) else int(r.shelf_life_days),
                       weight_g=None if pd.isna(r.weight_g) else float(r.weight_g)))
            have_sku.add(pid)
    await db.commit()
    await apply(db, [Move(int(r.product_id), str(r.warehouse_id), float(r.stock_on_hand), OPENING) for r in new],
                source="history", reason="New in the sales history")
    await load_cache(db)
    return len(new)
