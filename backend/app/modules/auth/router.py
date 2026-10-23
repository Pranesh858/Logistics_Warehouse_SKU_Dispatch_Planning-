import datetime as dt

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.auth import CurrentUser
from app.core.deps import DB
from app.core.security import DUMMY_HASH, create_token, hash_password, verify_password
from app.modules.users.models import AppUser
from app.modules.users.schemas import UserResponse

from app.core.audit import record
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

# Wrong passwords are counted per account. Enough of them pauses sign-in for a while, so a stolen username
# cannot be worked through password by password. Counts live in memory and clear when the service restarts.
_failures: dict[str, list[dt.datetime]] = {}


def _recent_failures(username: str) -> int:
    cutoff = dt.datetime.now() - dt.timedelta(minutes=settings.login_lockout_minutes)
    tries = [t for t in _failures.get(username, []) if t > cutoff]
    _failures[username] = tries
    return len(tries)


def _note_failure(username: str) -> None:
    _failures.setdefault(username, []).append(dt.datetime.now())


def reset_failures() -> None:
    _failures.clear()


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
    name = body.username.strip().lower()
    if _recent_failures(name) >= settings.login_max_failures:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many wrong passwords. Try again in {settings.login_lockout_minutes} minutes.")
    user = (await db.execute(select(AppUser).where(func.lower(AppUser.username) == name))).scalars().first()
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.active:
        _note_failure(name)
        if user is not None:
            await record(db, user, "login_failed", f"{_recent_failures(name)} wrong password(s) in the last {settings.login_lockout_minutes} minutes")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    _failures.pop(name, None)
    user.last_login_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    await db.commit()
    await record(db, user, "login", "", user.warehouse_id)
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
    user.must_change_password = False
    await db.commit()
    await record(db, user, "password_changed", "", user.warehouse_id)
    token, ttl = create_token(user.id, user.role, user.warehouse_id, user.password_hash)
    return TokenOut(access_token=token, expires_in=ttl, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser):
    return user
