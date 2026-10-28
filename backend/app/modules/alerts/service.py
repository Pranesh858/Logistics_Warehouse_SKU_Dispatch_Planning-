"""Raising, clearing and reading alerts.

Two things make an alert list worth having, and both are here rather than in the rules:

  * **One row per problem.** `raise_alert` is called whenever a condition is noticed, which may be every
    thirty seconds. The same `key` updates the existing row's count and timestamp instead of adding another.
  * **It clears itself.** `clear` is called when a condition is no longer true, which is what keeps the list
    a picture of now. A list that only ever grows gets ignored within a week, and an ignored alert is worse
    than none because it looks like cover.

Outside delivery happens once, when a problem first appears - not on every repeat, or a failing stock feed
would send a message every thirty seconds until somebody muted the channel.
"""
import asyncio
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.alerts import delivery
from app.modules.alerts.models import (
    ACKNOWLEDGED, CRITICAL, INFO, LIVE, OPEN, RESOLVED, SEVERITIES, WARNING, Alert,
)
from app.shared.exceptions import BadRequestError, NotFoundError

RANK = {CRITICAL: 0, WARNING: 1, INFO: 2}
KEEP_RESOLVED_DAYS = 30


async def raise_alert(db: AsyncSession, *, key: str, kind: str, severity: str, title: str, detail: str = "",
                      warehouse_id: str | None = None, product_id: int | None = None) -> Alert | None:
    """Record a problem. Returns the alert, or None if alerts are switched off.

    A problem that is already open is updated, not duplicated. One that was resolved and has come back is
    re-opened, because it is the same problem again and the count tells the story.
    """
    if not settings.alerts_enabled:
        return None
    if severity not in SEVERITIES:
        severity = WARNING
    existing = (await db.execute(select(Alert).where(Alert.dedupe_key == key))).scalars().first()
    now = datetime.now()

    if existing is None:
        alert = Alert(dedupe_key=key, kind=kind, severity=severity, status=OPEN, title=title,
                      detail=detail, warehouse_id=warehouse_id, product_id=product_id,
                      occurrences=1, first_seen=now, last_seen=now)
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        await _deliver(db, alert)
        return alert

    reopened = existing.status == RESOLVED
    existing.occurrences += 1
    existing.last_seen = now
    existing.severity, existing.title, existing.detail = severity, title, detail
    if reopened:
        existing.status, existing.resolved_at, existing.resolved_note = OPEN, None, None
        existing.acknowledged_by, existing.acknowledged_at = None, None
    await db.commit()
    await db.refresh(existing)
    if reopened:
        await _deliver(db, existing)         # it came back: that is news again
    return existing


async def _deliver(db: AsyncSession, alert: Alert) -> None:
    """Push to the configured channels, off the event loop. Delivery never breaks the caller."""
    if not delivery.channels():
        return
    try:
        result = await asyncio.to_thread(delivery.send, alert)
        if result:
            alert.delivery = result
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[alerts] delivery failed for {alert.dedupe_key}: {exc}", flush=True)


async def clear(db: AsyncSession, key: str, note: str = "The condition cleared on its own.") -> bool:
    """The condition is no longer true. Returns True if something was actually open."""
    alert = (await db.execute(select(Alert).where(Alert.dedupe_key == key))).scalars().first()
    if alert is None or alert.status == RESOLVED:
        return False
    alert.status, alert.resolved_at, alert.resolved_note = RESOLVED, datetime.now(), note
    await db.commit()
    return True


async def clear_missing(db: AsyncSession, kind: str, still_true: set[str]) -> int:
    """Resolve every open alert of this kind whose key is no longer in `still_true`.

    This is how a sweep of a rule closes what it no longer finds: the rule reports what is wrong now, and
    whatever is missing from that set has stopped being wrong.
    """
    rows = (await db.execute(select(Alert).where(Alert.kind == kind, Alert.status.in_(LIVE)))).scalars().all()
    gone = [a for a in rows if a.dedupe_key not in still_true]
    for a in gone:
        a.status, a.resolved_at = RESOLVED, datetime.now()
        a.resolved_note = "No longer the case."
    if gone:
        await db.commit()
    return len(gone)


# ----------------------------------------------------------------- reading
def view(a: Alert) -> dict:
    return {
        "id": a.id, "kind": a.kind, "severity": a.severity, "status": a.status, "title": a.title,
        "detail": a.detail, "warehouse_id": a.warehouse_id, "product_id": a.product_id,
        "occurrences": a.occurrences,
        "first_seen": a.first_seen.isoformat() if a.first_seen else None,
        "last_seen": a.last_seen.isoformat() if a.last_seen else None,
        "acknowledged_by": a.acknowledged_by,
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        "resolved_note": a.resolved_note,
        "delivery": a.delivery or None,
    }


async def listing(db: AsyncSession, warehouse_id: str | None = None, status: str | None = None,
                  limit: int = 200) -> list[dict]:
    """Live alerts, worst first, then most recent. A planner sees their own warehouse and anything global.

    An alert with no warehouse (a failed sales feed, a rejected retrain) concerns everyone, so it is shown
    to everyone: hiding it from a planner would mean nobody sees it until an admin logs in.
    """
    q = select(Alert)
    q = q.where(Alert.status == status.upper()) if status else q.where(Alert.status.in_(LIVE))
    rows = list((await db.execute(q.order_by(Alert.last_seen.desc()).limit(limit))).scalars())
    if warehouse_id:
        rows = [a for a in rows if a.warehouse_id in (None, warehouse_id)]
    rows.sort(key=lambda a: (RANK.get(a.severity, 3), -(a.last_seen.timestamp() if a.last_seen else 0)))
    return [view(a) for a in rows]


async def summary(db: AsyncSession, warehouse_id: str | None = None) -> dict:
    rows = await listing(db, warehouse_id)
    return {
        "open": len([a for a in rows if a["status"] == OPEN]),
        "acknowledged": len([a for a in rows if a["status"] == ACKNOWLEDGED]),
        "critical": len([a for a in rows if a["severity"] == CRITICAL]),
        "warning": len([a for a in rows if a["severity"] == WARNING]),
        "total": len(rows),
        "worst": rows[0]["severity"] if rows else None,
        "headline": rows[0]["title"] if rows else None,
        "enabled": settings.alerts_enabled,
        "channels": delivery.channels(),
    }


async def _get(db: AsyncSession, alert_id: int, warehouse_id: str | None) -> Alert:
    a = await db.get(Alert, alert_id)
    if a is None or (warehouse_id and a.warehouse_id not in (None, warehouse_id)):
        raise NotFoundError("Alert not found")
    return a


async def acknowledge(db: AsyncSession, alert_id: int, user: str, warehouse_id: str | None = None) -> dict:
    """Somebody is dealing with it. The alert stays in the list until the condition clears."""
    a = await _get(db, alert_id, warehouse_id)
    if a.status != OPEN:
        raise BadRequestError(f"This alert is already {a.status.lower()}")
    a.status, a.acknowledged_by, a.acknowledged_at = ACKNOWLEDGED, user, datetime.now()
    await db.commit()
    await db.refresh(a)
    return view(a)


async def resolve(db: AsyncSession, alert_id: int, user: str, note: str = "",
                  warehouse_id: str | None = None) -> dict:
    """Close it by hand. If the condition is still true, the next sweep raises it again - by design."""
    a = await _get(db, alert_id, warehouse_id)
    if a.status == RESOLVED:
        raise BadRequestError("This alert is already resolved")
    a.status, a.resolved_at = RESOLVED, datetime.now()
    a.resolved_note = note.strip() or f"Closed by {user}."
    await db.commit()
    await db.refresh(a)
    return view(a)


async def prune(db: AsyncSession, days: int = KEEP_RESOLVED_DAYS) -> int:
    """Forget resolved alerts older than `days`, so the table does not grow without end."""
    cutoff = datetime.now() - timedelta(days=days)
    rows = (await db.execute(select(Alert).where(Alert.status == RESOLVED,
                                                 Alert.resolved_at < cutoff))).scalars().all()
    for a in rows:
        await db.delete(a)
    if rows:
        await db.commit()
    return len(rows)


async def count_live(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(Alert)
                                 .where(Alert.status.in_(LIVE)))).scalar() or 0)
