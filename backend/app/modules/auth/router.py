import datetime as dt

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.auth import CurrentUser
from app.core.deps import DB
from app.core.security import DUMMY_HASH, create_token, hash_password, verify_password
from app.modules.users.models import AppUser
from app.modules.users.schemas import UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: DB):
    user = (await db.execute(select(AppUser).where(func.lower(AppUser.username) == body.username.strip().lower()))).scalars().first()
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    user.last_login_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    await db.commit()
    token, ttl = create_token(user.id, user.role, user.warehouse_id, user.password_hash)
    return TokenOut(access_token=token, expires_in=ttl, user=UserResponse.model_validate(user))


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password", response_model=TokenOut)
async def change_password(body: ChangePasswordIn, db: DB, user: CurrentUser):
    """Change your own password. Every other sign-in of yours stops working; the reply carries a fresh token for this one."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Your current password is not correct")
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a password different from the current one")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    token, ttl = create_token(user.id, user.role, user.warehouse_id, user.password_hash)
    return TokenOut(access_token=token, expires_in=ttl, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser):
    return user
