from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ROLE_ADMIN = "admin"        # sees and manages every warehouse and every user
ROLE_PLANNER = "planner"    # one warehouse: reviews, edits and approves its plan
ROLE_VIEWER = "viewer"      # read only
ROLES = (ROLE_ADMIN, ROLE_PLANNER, ROLE_VIEWER)


class AppUser(Base):
    """A person who can sign in. (A new table: the old open 'users' sample table is no longer used.)"""

    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(12))
    warehouse_id: Mapped[str | None] = mapped_column(String(10), nullable=True)   # planners (and optionally viewers) are tied to one warehouse
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)   # a password someone else set
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
