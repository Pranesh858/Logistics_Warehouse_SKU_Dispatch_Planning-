from fastapi import APIRouter, status

from app.core.audit import record
from app.core.auth import Admin
from app.core.deps import DB
from app.modules.users import service
from app.modules.users.schemas import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(db: DB, _: Admin):
    return await service.list_users(db)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, db: DB, admin: Admin):
    user = await service.create_user(db, body)
    await record(db, admin, "user_created", f"{user.username} as {user.role}" + (f" for {user.warehouse_id}" if user.warehouse_id else ""))
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, body: UserUpdate, db: DB, admin: Admin):
    """Change name, role, warehouse or password, or switch the account off (active = false)."""
    user = await service.update_user(db, user_id, body, admin)
    changed = [k for k in body.model_dump(exclude_unset=True) if k != "password"]
    if body.model_dump(exclude_unset=True).get("password"):
        changed.append("password reset")
    await record(db, admin, "user_changed", f"{user.username}: {', '.join(changed) or 'no change'}")
    return user
