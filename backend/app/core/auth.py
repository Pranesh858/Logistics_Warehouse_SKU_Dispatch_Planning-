"""Who is calling, and which warehouse they may touch."""
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.deps import DB
from app.core.security import decode_token, password_fingerprint
from app.modules.users.models import ROLE_ADMIN, ROLE_PLANNER, AppUser
from app.shared.exceptions import ForbiddenError

_bearer = HTTPBearer(auto_error=False, description="Token from POST /api/v1/auth/login")


async def get_current_user(db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> AppUser:
    unauthorised = HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorised
    claims = decode_token(creds.credentials)
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again.",
                            headers={"WWW-Authenticate": "Bearer"})
    user = await db.get(AppUser, int(claims["sub"]))
    if user is None or not user.active:             # re-checked every call, so switching a user off works at once
        raise unauthorised
    if claims.get("pv") != password_fingerprint(user.password_hash):   # the password changed since this token was issued
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your password was changed. Sign in again.",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[AppUser, Depends(get_current_user)]


def _require(*roles: str):
    async def dep(user: CurrentUser) -> AppUser:
        if user.role not in roles:
            raise ForbiddenError("Your role is not allowed to do this")
        return user
    return dep


Planner = Annotated[AppUser, Depends(_require(ROLE_PLANNER, ROLE_ADMIN))]   # may change plans (viewers may not)
Admin = Annotated[AppUser, Depends(_require(ROLE_ADMIN))]


def scope(user: AppUser) -> str | None:
    """The one warehouse this person is limited to, or None when they may see all of them."""
    return None if user.role == ROLE_ADMIN else user.warehouse_id


def ensure_warehouse(user: AppUser, warehouse_id: str) -> None:
    s = scope(user)
    if s is not None and warehouse_id != s:
        raise ForbiddenError(f"You work on {s} only; {warehouse_id} is not yours")


def pick_warehouse(user: AppUser, requested: str | None = None) -> str | None:
    """The warehouse a read should be limited to: the user's own, or whatever an unrestricted user asked for."""
    s = scope(user)
    if s is not None:
        if requested and requested != s:
            raise ForbiddenError(f"You work on {s} only; {requested} is not yours")
        return s
    return requested
