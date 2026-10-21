from fastapi import APIRouter, status

from app.core.auth import Admin
from app.core.deps import DB
from app.modules.users import service
from app.modules.users.schemas import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(db: DB, _: Admin):
    return await service.list_users(db)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, db: DB, _: Admin):
    return await service.create_user(db, body)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, body: UserUpdate, db: DB, admin: Admin):
    """Change name, role, warehouse or password, or switch the account off (active = false)."""
    return await service.update_user(db, user_id, body, admin)
