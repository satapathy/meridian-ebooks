"""Admin mode. Everything can be read without logging in; changing the library (upload, edit, delete, maintenance)
needs admin mode. The password comes from the ADMIN_PASSWORD environment variable (the user name is always "admin"). If it is
unset, access control is switched off and every write is allowed (the pre-existing behaviour)."""
import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from .config import settings

USER = "admin"   # fixed; only the password is configurable
COOKIE = "meridian_admin"
SESSION_SECONDS = 12 * 3600
MAX_FAILS, LOCK_SECONDS = 5, 60

router = APIRouter(prefix="/auth", tags=["Auth"])
_fails: dict[str, tuple[int, float]] = {}   # client ip -> (consecutive failures, locked until)


def enabled() -> bool:
    return bool(settings.admin_password)


def _key() -> bytes:
    # derived from the password: sessions survive a restart and stop working when the password changes
    return hashlib.sha256(f"meridian-session|{settings.admin_password}".encode()).digest()


def _sig(payload: str) -> str:
    return hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(8)}"
    return f"{payload}.{_sig(payload)}"


def valid_token(token: str | None) -> bool:
    try:
        exp, nonce, sig = (token or "").split(".")
        return int(exp) > time.time() and hmac.compare_digest(sig, _sig(f"{exp}.{nonce}"))
    except ValueError:
        return False


def check_credentials(user: str, password: str) -> bool:
    ok_user = hmac.compare_digest(user.encode(), USER.encode())
    ok_pass = hmac.compare_digest(password.encode(), settings.admin_password.encode())
    return ok_user and ok_pass


_basic = HTTPBasic(auto_error=False, description="User name `admin` and the admin password (the same password as the web UI's Admin mode)")


def is_admin(request: Request, creds: HTTPBasicCredentials | None = None) -> bool:
    if not enabled():
        return True
    if creds and check_credentials(creds.username, creds.password):    # scripts and Swagger's Authorize button
        return True
    return valid_token(request.cookies.get(COOKIE))


def require_admin(request: Request, creds: HTTPBasicCredentials | None = Depends(_basic)) -> None:
    """Dependency for every route that changes the library. Also puts the Authorize button into Swagger."""
    if not is_admin(request, creds):
        raise HTTPException(401, "Admin mode required - log in as admin first")


class Login(BaseModel):
    password: str


def _status(request: Request) -> dict:
    return {"auth_enabled": enabled(), "admin": is_admin(request)}


@router.get("/status", summary="Is access control on, and is this browser in admin mode?")
def status(request: Request):
    return _status(request)


@router.post("/login", summary="Enter admin mode",
             description="Sets an HttpOnly session cookie (12 hours). Five wrong attempts lock the client out for a minute.")
def login(body: Login, request: Request, response: Response):
    if not enabled():
        raise HTTPException(400, "Admin mode is not configured on this server (set ADMIN_PASSWORD)")
    ip = request.client.host if request.client else "?"
    count, until = _fails.get(ip, (0, 0.0))
    if until > time.time():
        raise HTTPException(429, f"Too many attempts - try again in {int(until - time.time()) + 1}s")
    if not check_credentials(USER, body.password):
        count += 1
        _fails[ip] = (0, time.time() + LOCK_SECONDS) if count >= MAX_FAILS else (count, 0.0)
        raise HTTPException(401, "Wrong password")
    _fails.pop(ip, None)
    response.set_cookie(COOKIE, make_token(), max_age=SESSION_SECONDS, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")
    return {"auth_enabled": True, "admin": True}


@router.post("/logout", summary="Leave admin mode")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"admin": False}
