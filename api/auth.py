"""
Login for the one owner of this app. Every route except /health and /auth/* needs a session.

Settings (environment / .env, never in code):
  APP_USERNAME        the login name
  APP_PASSWORD_HASH   a scrypt hash of the password: make it with  python -m scripts.hash_password
  SESSION_HOURS       how long a login lasts (default 8)
  AUTH_COOKIE_SECURE  "true" (default) = cookie only over HTTPS; set "false" for local http
  API_CORS_ORIGINS    website address(es) allowed to call the API (default http://localhost:3000)

The password is never stored, only a salted scrypt hash checked in constant time. A login gives a
random 256-bit session id in an HttpOnly, SameSite=Strict cookie; the server keeps only its SHA-256.
Wrong logins lock out (5 per client or 20 in total within 15 minutes). Changing requests from other
websites are refused. Sessions live in memory: restarting the API logs everyone out.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

COOKIE = "vq_session"
PUBLIC_PATHS = {"/health", "/auth/login", "/auth/logout", "/auth/me"}
CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
MAX_SESSIONS = 10
FAILS_PER_CLIENT = 5
FAILS_TOTAL = 20
LOCK_SECONDS = 15 * 60
_SCRYPT = {"n": 2**15, "r": 8, "p": 1}      # ~32 MB and ~0.1 s per check: slow for guessing, fine for one login
_MAXMEM = 64 * 1024 * 1024

# ----------------------------------------------------------------------------- settings (read when used)

def allowed_origins() -> list[str]:
    raw = os.getenv("API_CORS_ORIGINS", "http://localhost:3000")
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]

def _cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "true").strip().lower() != "false"

def _session_seconds() -> int:
    try:
        hours = float(os.getenv("SESSION_HOURS", "8"))
    except ValueError:
        hours = 8.0
    return int(min(max(hours, 0.25), 72) * 3600)

def _credentials() -> tuple[str, str]:
    user = os.getenv("APP_USERNAME", "").strip()
    stored = os.getenv("APP_PASSWORD_HASH", "").strip().strip("'\"")
    if not user or not stored.startswith("scrypt:"):
        raise HTTPException(503, "Login is not set up on the server (APP_USERNAME / APP_PASSWORD_HASH).")
    return user, stored

# ----------------------------------------------------------------------------- passwords

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")

def hash_password(password: str) -> str:
    """A salted scrypt hash, written as scrypt:n:r:p:salt:hash (safe to keep in .env)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, maxmem=_MAXMEM, **_SCRYPT)
    return f"scrypt:{_SCRYPT['n']}:{_SCRYPT['r']}:{_SCRYPT['p']}:{_b64(salt)}:{_b64(digest)}"

def _verify(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split(":")
        expected = base64.urlsafe_b64decode(digest)
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.urlsafe_b64decode(salt),
                             n=int(n), r=int(r), p=int(p), dklen=len(expected), maxmem=_MAXMEM)
    except (ValueError, TypeError):
        return False
    return kind == "scrypt" and hmac.compare_digest(got, expected)

# ----------------------------------------------------------------------------- sessions and lockout

class _Sessions:
    """Live sessions, keyed by a SHA-256 of the cookie value."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ends: dict[str, float] = {}

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def start(self, seconds: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._ends = {k: t for k, t in self._ends.items() if t > now}
            while len(self._ends) >= MAX_SESSIONS:            # drop the one ending soonest
                del self._ends[min(self._ends, key=self._ends.__getitem__)]
            self._ends[self._key(token)] = now + seconds
        return token

    def valid(self, token: str | None) -> bool:
        if not token or len(token) > 128:
            return False
        key = self._key(token)
        with self._lock:
            ends = self._ends.get(key)
            if ends is not None and ends <= time.time():
                del self._ends[key]
                ends = None
        return ends is not None

    def end(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._ends.pop(self._key(token), None)

class _Lockout:
    """Wrong logins in the last LOCK_SECONDS, per client and in total."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    def wait_seconds(self, client: str) -> int:
        now = time.time()
        with self._lock:
            for key in list(self._fails):
                recent = [t for t in self._fails[key] if now - t < LOCK_SECONDS]
                if recent:
                    self._fails[key] = recent
                else:
                    del self._fails[key]
            mine = list(self._fails.get(client, []))
            everyone = sorted(t for times in self._fails.values() for t in times)
        until = 0.0
        if len(mine) >= FAILS_PER_CLIENT:
            until = max(until, mine[-FAILS_PER_CLIENT] + LOCK_SECONDS)
        if len(everyone) >= FAILS_TOTAL:
            until = max(until, everyone[-FAILS_TOTAL] + LOCK_SECONDS)
        return int(until - now) + 1 if until > now else 0

    def failed(self, client: str) -> None:
        with self._lock:
            self._fails.setdefault(client, []).append(time.time())

    def succeeded(self, client: str) -> None:
        with self._lock:
            self._fails.pop(client, None)

SESSIONS = _Sessions()
LOCKOUT = _Lockout()

# ----------------------------------------------------------------------------- routes

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)

def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"

@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    user, stored = _credentials()
    client = _client(request)
    wait = LOCKOUT.wait_seconds(client)
    if wait:
        raise HTTPException(429, "Too many failed logins. Try again later.", headers={"Retry-After": str(wait)})
    name_ok = hmac.compare_digest(body.username.strip().encode("utf-8"), user.encode("utf-8"))
    password_ok = _verify(body.password, stored)      # always checked, so timing does not reveal the username
    if not (name_ok and password_ok):
        LOCKOUT.failed(client)
        raise HTTPException(401, "Wrong username or password.")
    LOCKOUT.succeeded(client)
    SESSIONS.end(request.cookies.get(COOKIE))          # every login gets a fresh session id
    seconds = _session_seconds()
    response.set_cookie(COOKIE, SESSIONS.start(seconds), max_age=seconds, path="/",
                        httponly=True, secure=_cookie_secure(), samesite="strict")
    return {"user": user}

@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    SESSIONS.end(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=_cookie_secure(), samesite="strict")
    return {"ok": True}

@router.get("/me")
def me(request: Request) -> dict:
    if not SESSIONS.valid(request.cookies.get(COOKIE)):
        raise HTTPException(401, "Please log in.")
    return {"user": os.getenv("APP_USERNAME", "").strip()}

# ----------------------------------------------------------------------------- the guard on every request

async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Refuses changing requests from other websites, and any request without a session."""
    if request.method in CHANGING:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in allowed_origins():
            return JSONResponse({"detail": "Requests from this website are not allowed."}, status_code=403)
    if (request.method != "OPTIONS" and request.url.path not in PUBLIC_PATHS
            and not SESSIONS.valid(request.cookies.get(COOKIE))):
        return JSONResponse({"detail": "Please log in."}, status_code=401)
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response
