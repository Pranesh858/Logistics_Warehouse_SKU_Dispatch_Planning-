"""Password hashing (PBKDF2, standard library) and signed login tokens (JWT)."""
import base64
import datetime as dt
import hashlib
import hmac
import secrets

import jwt

from app.core.config import settings

_ALGO = "HS256"


def hash_password(password: str, iterations: int | None = None) -> str:
    iterations = iterations or settings.password_iterations
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(calc, base64.b64decode(digest))
    except Exception:
        return False


# Used when the username does not exist, so a wrong username and a wrong password take the same time.
DUMMY_HASH = hash_password(secrets.token_urlsafe(8), 1000)


def password_fingerprint(stored_hash: str) -> str:
    """A short fingerprint of the stored password. It goes into every login token, so changing or resetting
    the password makes all older tokens stop working (without a schema change)."""
    return hashlib.sha256(stored_hash.encode()).hexdigest()[:16]


def create_token(user_id: int, role: str, warehouse_id: str | None, stored_hash: str) -> tuple[str, int]:
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.access_token_minutes)
    token = jwt.encode({"sub": str(user_id), "role": role, "wh": warehouse_id, "pv": password_fingerprint(stored_hash), "exp": expires},
                       settings.secret_key, algorithm=_ALGO)
    return token, settings.access_token_minutes * 60


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None
