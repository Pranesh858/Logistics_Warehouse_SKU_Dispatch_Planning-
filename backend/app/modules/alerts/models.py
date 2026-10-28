from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Severity, in the order a planner should care about them.
INFO, WARNING, CRITICAL = "INFO", "WARNING", "CRITICAL"
SEVERITIES = (CRITICAL, WARNING, INFO)

# Lifecycle:  OPEN -> ACKNOWLEDGED  (somebody is dealing with it)
#             OPEN | ACKNOWLEDGED -> RESOLVED  (the condition went away, or someone closed it)
OPEN, ACKNOWLEDGED, RESOLVED = "OPEN", "ACKNOWLEDGED", "RESOLVED"
LIVE = (OPEN, ACKNOWLEDGED)


class Alert(Base):
    """Something that needs a person.

    One row per *problem*, not per occurrence. A stock feed that fails every five minutes is one alert with
    a rising count, not 288 rows a day: a list nobody can read is the same as no alerts at all. `dedupe_key`
    is what makes two occurrences the same problem.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(14), default=OPEN, index=True)
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    warehouse_id: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which outside channels this alert was pushed to, and whether that worked. In-app needs no delivery:
    # the row above is the delivery.
    delivery: Mapped[str] = mapped_column(Text, default="")
