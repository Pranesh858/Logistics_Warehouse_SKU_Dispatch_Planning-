import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.modules.forecast.runtime import runtime
from app.modules.users.models import ROLE_ADMIN, ROLE_PLANNER, ROLE_VIEWER, AppUser
from app.modules.users.schemas import UserCreate, UserUpdate
from app.shared.exceptions import BadRequestError, ConflictError, NotFoundError


async def _warehouses() -> set[str]:
    return set((await asyncio.to_thread(runtime.stock_snapshot))["warehouse_id"])


async def _check_scope(role: str, warehouse_id: str | None) -> None:
    if role == ROLE_PLANNER and not warehouse_id:
        raise BadRequestError("A planner must be assigned to a warehouse")
    if role == ROLE_ADMIN and warehouse_id:
        raise BadRequestError("An admin sees every warehouse, so no warehouse can be assigned")
    if warehouse_id and warehouse_id not in await _warehouses():
        raise BadRequestError(f"Unknown warehouse {warehouse_id}")


async def list_users(db: AsyncSession) -> list[AppUser]:
    return list((await db.execute(select(AppUser).order_by(AppUser.role, AppUser.warehouse_id, AppUser.username))).scalars())


async def create_user(db: AsyncSession, data: UserCreate) -> AppUser:
    await _check_scope(data.role, data.warehouse_id)
    if (await db.execute(select(AppUser).where(func.lower(AppUser.username) == data.username.lower()))).scalars().first():
        raise ConflictError(f"Username {data.username} is already taken")
    user = AppUser(username=data.username, name=data.name.strip(), password_hash=hash_password(data.password),
                   role=data.role, warehouse_id=data.warehouse_id)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user_id: int, data: UserUpdate, acting: AppUser) -> AppUser:
    user = await db.get(AppUser, user_id)
    if user is None:
        raise NotFoundError("User not found")
    fields = data.model_dump(exclude_unset=True)
    role = fields.get("role", user.role)
    wh = fields.get("warehouse_id", user.warehouse_id) if "warehouse_id" in fields else user.warehouse_id
    if role == ROLE_ADMIN:
        wh = None
    await _check_scope(role, wh)
    if user.id == acting.id and (fields.get("active") is False or (role != ROLE_ADMIN)):
        raise BadRequestError("You cannot switch off or demote your own account")
    if "name" in fields and fields["name"]:
        user.name = fields["name"].strip()
    if fields.get("password"):
        user.password_hash = hash_password(fields["password"])
    if "active" in fields and fields["active"] is not None:
        user.active = fields["active"]
    user.role, user.warehouse_id = role, wh
    await db.commit()
    await db.refresh(user)
    return user


async def seed_users(db: AsyncSession) -> int:
    """First start: one admin, one viewer and one planner per warehouse (all with the demo password)."""
    if not settings.seed_users_on_startup:
        return 0
    if (await db.execute(select(func.count()).select_from(AppUser))).scalar():
        return 0
    pw = hash_password(settings.demo_password)
    rows = [AppUser(username="admin", name="Planning Admin", password_hash=pw, role=ROLE_ADMIN),
            AppUser(username="viewer", name="Operations Viewer", password_hash=pw, role=ROLE_VIEWER)]
    for wh in sorted(await _warehouses()):
        rows.append(AppUser(username=f"planner.{wh.lower()}", name=f"{wh} Planner", password_hash=pw,
                            role=ROLE_PLANNER, warehouse_id=wh))
    db.add_all(rows)
    await db.commit()
    return len(rows)
