"""Who did what. Approvals, user changes and connection changes are recorded so they can be answered for later."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    username: Mapped[str] = mapped_column(String(60), index=True)
    role: Mapped[str] = mapped_column(String(12), default="")
    action: Mapped[str] = mapped_column(String(40), index=True)
    warehouse_id: Mapped[str | None] = mapped_column(String(10), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


async def record(db: AsyncSession, user, action: str, detail: str = "", warehouse_id: str | None = None) -> None:
    """Never let bookkeeping break the action it is recording."""
    try:
        db.add(AuditEntry(username=getattr(user, "username", str(user)), role=getattr(user, "role", ""),
                          action=action, detail=detail[:2000], warehouse_id=warehouse_id))
        await db.commit()
    except Exception:
        await db.rollback()


async def recent(db: AsyncSession, limit: int = 100, action: str | None = None) -> list[dict]:
    q = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
    if action:
        q = q.where(AuditEntry.action == action)
    return [{"id": r.id, "at": r.at.isoformat() if r.at else None, "username": r.username, "role": r.role,
             "action": r.action, "warehouse_id": r.warehouse_id, "detail": r.detail}
            for r in (await db.execute(q)).scalars().all()]
